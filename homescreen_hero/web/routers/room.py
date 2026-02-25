# Movie Night room-code API — Phase 3B (remote multiplayer)

import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from homescreen_hero.core.auth import CurrentUser, get_current_user
from homescreen_hero.core.db.base import session_scope
from homescreen_hero.core.db.models import MovieNightSession, SessionPlayer
from homescreen_hero.core.db.vibes import get_ranked_movies_by_vibes_group
from homescreen_hero.core.room_codes import generate_room_code
from homescreen_hero.core.vibe_scoring import VIBE_NAMES, VIBE_DISPLAY_NAMES
from homescreen_hero.web.rate_limit import limiter
from homescreen_hero.web.routers.movie_night import (
    TMDB_IMAGE_BASE,
    VALID_DURATIONS,
    VALID_REWATCH_MODES,
    _get_user_watched_keys,
    _build_movie_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/movie-night/room", tags=["movie-night-room"])

SESSION_DURATION_MINUTES = 60
ACTIVE_STATES = {"waiting", "voting"}


# --- Request / Response models ---


class RoomCreateRequest(BaseModel):
    duration: Optional[str] = None
    rewatch_mode: Optional[str] = "new"
    max_players: int = 4

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_DURATIONS:
            raise ValueError(f"Invalid duration: {v}")
        return v

    @field_validator("rewatch_mode")
    @classmethod
    def validate_rewatch_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_REWATCH_MODES:
            raise ValueError(f"Invalid rewatch_mode: {v}")
        return v

    @field_validator("max_players")
    @classmethod
    def validate_max_players(cls, v: int) -> int:
        if v < 2 or v > 8:
            raise ValueError("max_players must be between 2 and 8")
        return v


class RoomCreateResponse(BaseModel):
    room_code: str
    host_player_token: str
    expires_at: str


class RoomJoinRequest(BaseModel):
    room_code: str
    player_name: str

    @field_validator("player_name")
    @classmethod
    def validate_player_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 20:
            raise ValueError("Player name must be 1-20 characters")
        return v


class RoomJoinResponse(BaseModel):
    player_token: str
    session_state: str
    players: List["PlayerInfo"]
    host_name: str


class VibesSubmitRequest(BaseModel):
    vibes: List[str]

    @field_validator("vibes")
    @classmethod
    def validate_vibes(cls, v: List[str]) -> List[str]:
        if len(v) < 1:
            raise ValueError("Must select at least 1 vibe")
        for vibe in v:
            if vibe not in VIBE_NAMES:
                raise ValueError(f"Unknown vibe: {vibe}")
        return v


class VoteRequest(BaseModel):
    approve: bool


class PlayerInfo(BaseModel):
    player_name: str
    is_host: bool
    has_submitted_vibes: bool


class GuestMovieInfo(BaseModel):
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    genres: Optional[List[str]] = None
    duration_minutes: Optional[int] = None
    match_score: float


class RoomPollResponse(BaseModel):
    room_code: str
    state: str
    players: List[PlayerInfo]
    host_name: str
    your_player_name: str
    vibes_submitted_count: int
    current_movie: Optional[GuestMovieInfo] = None
    current_movie_index: int = 0
    total_movies: int = 0
    votes: Optional[Dict[str, Optional[bool]]] = None
    approved_movie: Optional[GuestMovieInfo] = None
    filters_applied: Optional[Dict[str, str]] = None


# --- Helpers ---


def _get_session_and_player(token: str):
    # Look up session + player from a player token. Returns (session, player) or raises 404.
    with session_scope() as db:
        player = db.query(SessionPlayer).filter(
            SessionPlayer.player_token == token
        ).first()
        if not player:
            raise HTTPException(status_code=404, detail="Invalid player token")

        session = db.query(MovieNightSession).filter(
            MovieNightSession.id == player.session_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Lazy expiry check
        if session.state in ACTIVE_STATES and datetime.utcnow() > session.expires_at:
            session.state = "expired"
            session.updated_at = datetime.utcnow()

        db.expunge(session)
        db.expunge(player)

        players = db.query(SessionPlayer).filter(
            SessionPlayer.session_id == session.id
        ).all()
        for p in players:
            db.expunge(p)

    return session, player, players


def _build_poll_response(
    session: MovieNightSession, players: list, current_player: SessionPlayer | None = None,
) -> RoomPollResponse:
    host = next((p for p in players if p.is_host), None)
    player_infos = [
        PlayerInfo(
            player_name=p.player_name,
            is_host=p.is_host,
            has_submitted_vibes=p.vibes is not None,
        )
        for p in players
    ]

    current_movie = None
    approved_movie = None
    total_movies = 0
    votes = None

    if session.match_results:
        total_movies = len(session.match_results)

    if session.state == "voting" and session.match_results:
        idx = session.current_movie_index
        if idx < len(session.match_results):
            current_movie = GuestMovieInfo(**session.match_results[idx])
        votes = {p.player_name: p.current_vote for p in players}

    if session.state == "approved" and session.match_results:
        idx = session.current_movie_index
        if idx < len(session.match_results):
            approved_movie = GuestMovieInfo(**session.match_results[idx])

    your_name = current_player.player_name if current_player else (host.player_name if host else "Unknown")

    return RoomPollResponse(
        room_code=session.room_code,
        state=session.state,
        players=player_infos,
        host_name=host.player_name if host else "Unknown",
        your_player_name=your_name,
        vibes_submitted_count=sum(1 for p in players if p.vibes is not None),
        current_movie=current_movie,
        current_movie_index=session.current_movie_index,
        total_movies=total_movies,
        votes=votes,
        approved_movie=approved_movie,
        filters_applied=session.filters_applied,
    )


def _evaluate_votes(players: list) -> str:
    # Returns "approved", "next", or "pending".
    votes = [p.current_vote for p in players]
    if any(v is None for v in votes):
        return "pending"
    approvals = sum(1 for v in votes if v)
    total = len(votes)
    if total <= 2:
        return "approved" if approvals == total else "next"
    return "approved" if approvals > total / 2 else "next"


def _build_guest_movie_dict(movie_data: dict) -> dict:
    # Strip internal fields from a movie dict for guest responses.
    return {
        "title": movie_data["title"],
        "year": movie_data.get("year"),
        "poster_url": movie_data.get("poster_url"),
        "overview": movie_data.get("overview"),
        "genres": movie_data.get("genres"),
        "duration_minutes": movie_data.get("duration_minutes"),
        "match_score": movie_data["match_score"],
    }


# --- Endpoints ---


@router.post("/create", response_model=RoomCreateResponse)
@limiter.limit("3/minute")
def create_room(
    request: Request,
    body: RoomCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> RoomCreateResponse:
    room_code = generate_room_code()
    now = datetime.utcnow()
    host_token = secrets.token_hex(16)

    with session_scope() as db:
        session = MovieNightSession(
            room_code=room_code,
            state="waiting",
            host_user_id=current_user.id,
            host_username=current_user.username,
            duration_filter=body.duration,
            rewatch_mode=body.rewatch_mode or "new",
            max_players=body.max_players,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(minutes=SESSION_DURATION_MINUTES),
        )
        db.add(session)
        db.flush()

        host_player = SessionPlayer(
            session_id=session.id,
            player_name=current_user.username,
            is_host=True,
            player_token=host_token,
            joined_at=now,
        )
        db.add(host_player)

    return RoomCreateResponse(
        room_code=room_code,
        host_player_token=host_token,
        expires_at=(now + timedelta(minutes=SESSION_DURATION_MINUTES)).isoformat(),
    )


@router.post("/join", response_model=RoomJoinResponse)
@limiter.limit("5/minute")
def join_room(
    request: Request,
    body: RoomJoinRequest,
) -> RoomJoinResponse:
    code = body.room_code.strip().upper()
    now = datetime.utcnow()

    with session_scope() as db:
        session = db.query(MovieNightSession).filter(
            MovieNightSession.room_code == code,
        ).first()

        if not session or session.state not in ACTIVE_STATES or now > session.expires_at:
            raise HTTPException(status_code=404, detail="Room not found or expired")

        if session.state != "waiting":
            raise HTTPException(status_code=409, detail="Room is no longer accepting players")

        existing_players = db.query(SessionPlayer).filter(
            SessionPlayer.session_id == session.id,
        ).all()

        if len(existing_players) >= session.max_players:
            raise HTTPException(status_code=409, detail="Room is full")

        # Deduplicate names
        existing_names = {p.player_name.lower() for p in existing_players}
        name = body.player_name
        if name.lower() in existing_names:
            suffix = 2
            while f"{name}{suffix}".lower() in existing_names:
                suffix += 1
            name = f"{name}{suffix}"

        player_token = secrets.token_hex(16)
        new_player = SessionPlayer(
            session_id=session.id,
            player_name=name,
            is_host=False,
            player_token=player_token,
            joined_at=now,
        )
        db.add(new_player)
        db.flush()

        # Re-fetch players for response
        all_players = db.query(SessionPlayer).filter(
            SessionPlayer.session_id == session.id,
        ).all()

        host = next((p for p in all_players if p.is_host), None)
        player_infos = [
            PlayerInfo(
                player_name=p.player_name,
                is_host=p.is_host,
                has_submitted_vibes=p.vibes is not None,
            )
            for p in all_players
        ]

    return RoomJoinResponse(
        player_token=player_token,
        session_state=session.state,
        players=player_infos,
        host_name=host.player_name if host else "Unknown",
    )


@router.get("/poll", response_model=RoomPollResponse)
@limiter.limit("200/minute")
def poll_room(
    request: Request,
    token: str = Query(...),
) -> RoomPollResponse:
    session, player, players = _get_session_and_player(token)
    return _build_poll_response(session, players, current_player=player)


@router.post("/vibes")
@limiter.limit("5/minute")
def submit_vibes(
    request: Request,
    body: VibesSubmitRequest,
    token: str = Query(...),
):
    with session_scope() as db:
        player = db.query(SessionPlayer).filter(
            SessionPlayer.player_token == token,
        ).first()
        if not player:
            raise HTTPException(status_code=404, detail="Invalid player token")

        session = db.query(MovieNightSession).filter(
            MovieNightSession.id == player.session_id,
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.state != "waiting":
            raise HTTPException(status_code=409, detail="Vibes can only be submitted during waiting phase")

        if datetime.utcnow() > session.expires_at:
            session.state = "expired"
            session.updated_at = datetime.utcnow()
            raise HTTPException(status_code=410, detail="Session expired")

        player.vibes = body.vibes

        all_players = db.query(SessionPlayer).filter(
            SessionPlayer.session_id == session.id,
        ).all()

        db.flush()
        for p in all_players:
            db.expunge(p)
        db.expunge(session)

    current_player = next((p for p in all_players if p.player_token == token), None)
    return _build_poll_response(session, all_players, current_player=current_player)


@router.post("/start-matching", response_model=RoomPollResponse)
@limiter.limit("3/minute")
def start_matching(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    token: str = Query(...),
):
    with session_scope() as db:
        player = db.query(SessionPlayer).filter(
            SessionPlayer.player_token == token,
        ).first()
        if not player or not player.is_host:
            raise HTTPException(status_code=403, detail="Only the host can start matching")

        session = db.query(MovieNightSession).filter(
            MovieNightSession.id == player.session_id,
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.host_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the host can start matching")

        if session.state != "waiting":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start matching in state '{session.state}'"
            )

        if datetime.utcnow() > session.expires_at:
            session.state = "expired"
            session.updated_at = datetime.utcnow()
            raise HTTPException(status_code=410, detail="Session expired")

        all_players = db.query(SessionPlayer).filter(
            SessionPlayer.session_id == session.id,
        ).all()

        if not all(p.vibes for p in all_players):
            raise HTTPException(status_code=409, detail="Not all players have submitted vibes")

        if len(all_players) < 2:
            raise HTTPException(status_code=409, detail="Need at least 2 players")

        # Collect vibes from all players
        player_vibes = [p.vibes for p in all_players if p.vibes]

        # Handle rewatch mode (host's Plex account)
        filters_applied: Dict[str, str] = {}
        exclude_keys = None
        only_keys = None

        rewatch = session.rewatch_mode or "any"
        if rewatch in ("new", "rewatch"):
            watched_keys = _get_user_watched_keys(current_user.username)
            if watched_keys is not None:
                if rewatch == "new":
                    exclude_keys = watched_keys
                    filters_applied["rewatch_mode"] = "new"
                else:
                    only_keys = watched_keys
                    filters_applied["rewatch_mode"] = "rewatch"
            else:
                filters_applied["rewatch_mode"] = "any"
                filters_applied["rewatch_fallback"] = "plex_unavailable"
        else:
            filters_applied["rewatch_mode"] = "any"

        if session.duration_filter:
            filters_applied["duration"] = session.duration_filter

        # Compute group match
        ranked = get_ranked_movies_by_vibes_group(
            player_vibes,
            limit=10,
            duration_bucket=session.duration_filter,
            exclude_rating_keys=exclude_keys,
            only_rating_keys=only_keys,
        )

        # Fallback: drop duration filter if too few results
        if len(ranked) < 10 and session.duration_filter:
            ranked = get_ranked_movies_by_vibes_group(
                player_vibes,
                limit=10,
                duration_bucket=None,
                exclude_rating_keys=exclude_keys,
                only_rating_keys=only_keys,
            )
            filters_applied.pop("duration", None)
            filters_applied["duration_fallback"] = "dropped"

        # Convert to guest-safe movie dicts and store in session
        full_movies = _build_movie_response(ranked)
        guest_movie_dicts = [
            _build_guest_movie_dict(m.model_dump()) for m in full_movies
        ]

        session.match_results = guest_movie_dicts
        session.filters_applied = filters_applied
        session.current_movie_index = 0
        session.state = "voting"
        session.updated_at = datetime.utcnow()

        # Clear all votes
        for p in all_players:
            p.current_vote = None

        # Re-fetch for response
        db.flush()
        for p in all_players:
            db.expunge(p)
        db.expunge(session)

    current_player = next((p for p in all_players if p.player_token == token), None)
    return _build_poll_response(session, all_players, current_player=current_player)


@router.post("/vote", response_model=RoomPollResponse)
@limiter.limit("10/minute")
def vote_on_movie(
    request: Request,
    body: VoteRequest,
    token: str = Query(...),
):
    with session_scope() as db:
        player = db.query(SessionPlayer).filter(
            SessionPlayer.player_token == token,
        ).first()
        if not player:
            raise HTTPException(status_code=404, detail="Invalid player token")

        session = db.query(MovieNightSession).filter(
            MovieNightSession.id == player.session_id,
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.state != "voting":
            raise HTTPException(status_code=409, detail="Not in voting phase")

        if datetime.utcnow() > session.expires_at:
            session.state = "expired"
            session.updated_at = datetime.utcnow()
            raise HTTPException(status_code=410, detail="Session expired")

        # Record vote
        player.current_vote = body.approve

        all_players = db.query(SessionPlayer).filter(
            SessionPlayer.session_id == session.id,
        ).all()

        result = _evaluate_votes(all_players)

        if result == "approved":
            session.state = "approved"
            session.updated_at = datetime.utcnow()
        elif result == "next":
            session.current_movie_index += 1
            if session.match_results and session.current_movie_index >= len(session.match_results):
                session.state = "exhausted"
            else:
                # Clear all votes for next round
                for p in all_players:
                    p.current_vote = None
            session.updated_at = datetime.utcnow()
        # "pending" = do nothing, wait for more votes

        db.flush()
        for p in all_players:
            db.expunge(p)
        db.expunge(session)

    current_player = next((p for p in all_players if p.player_token == token), None)
    return _build_poll_response(session, all_players, current_player=current_player)


@router.delete("/{room_code}", status_code=204)
@limiter.limit("3/minute")
def cancel_room(
    request: Request,
    room_code: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    with session_scope() as db:
        session = db.query(MovieNightSession).filter(
            MovieNightSession.room_code == room_code.upper(),
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Room not found")

        if session.host_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the host can cancel this room")

        session.state = "expired"
        session.updated_at = datetime.utcnow()
