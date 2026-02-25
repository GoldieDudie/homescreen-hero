import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from homescreen_hero.core.db.base import session_scope
from homescreen_hero.core.db.models import MovieNightSession, SessionPlayer
from homescreen_hero.core.room_codes import ALPHABET
from homescreen_hero.web.app import create_app
from homescreen_hero.web.routers.room import _evaluate_votes


# --- Room code generation ---


class TestRoomCodeGeneration:
    def test_alphabet_excludes_ambiguous(self):
        for char in "OIL01":
            assert char not in ALPHABET

    def test_alphabet_length(self):
        assert len(ALPHABET) == 31


# --- Voting logic ---


class TestEvaluateVotes:
    def _make_player(self, vote):
        return type("P", (), {"current_vote": vote, "player_name": "test"})()

    def test_pending_when_not_all_voted(self):
        players = [self._make_player(True), self._make_player(None)]
        assert _evaluate_votes(players) == "pending"

    def test_two_players_unanimous_approve(self):
        players = [self._make_player(True), self._make_player(True)]
        assert _evaluate_votes(players) == "approved"

    def test_two_players_one_reject(self):
        players = [self._make_player(True), self._make_player(False)]
        assert _evaluate_votes(players) == "next"

    def test_two_players_both_reject(self):
        players = [self._make_player(False), self._make_player(False)]
        assert _evaluate_votes(players) == "next"

    def test_three_players_majority_approve(self):
        players = [self._make_player(True), self._make_player(True), self._make_player(False)]
        assert _evaluate_votes(players) == "approved"

    def test_three_players_majority_reject(self):
        players = [self._make_player(False), self._make_player(False), self._make_player(True)]
        assert _evaluate_votes(players) == "next"

    def test_four_players_tie_is_reject(self):
        players = [
            self._make_player(True), self._make_player(True),
            self._make_player(False), self._make_player(False),
        ]
        assert _evaluate_votes(players) == "next"

    def test_four_players_three_approve(self):
        players = [
            self._make_player(True), self._make_player(True),
            self._make_player(True), self._make_player(False),
        ]
        assert _evaluate_votes(players) == "approved"

    def test_all_pending(self):
        players = [self._make_player(None), self._make_player(None)]
        assert _evaluate_votes(players) == "pending"


# --- API integration tests ---
# Auth is disabled in test env, so get_current_user returns anonymous admin.


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def create_test_room(client):
    # Helper that creates a room and returns (room_code, host_token)
    def _create(duration=None, rewatch_mode="any", max_players=4):
        res = client.post(
            "/api/movie-night/room/create",
            json={"duration": duration, "rewatch_mode": rewatch_mode, "max_players": max_players},
        )
        assert res.status_code == 200
        data = res.json()
        return data["room_code"], data["host_player_token"]
    return _create


class TestCreateRoom:
    def test_creates_room(self, client):
        res = client.post(
            "/api/movie-night/room/create",
            json={"rewatch_mode": "any"},
        )
        assert res.status_code == 200
        data = res.json()
        assert re.match(r"^HERO-[A-Z0-9]{4}$", data["room_code"])
        assert len(data["host_player_token"]) == 32
        assert "expires_at" in data

    def test_invalid_duration(self, client):
        res = client.post(
            "/api/movie-night/room/create",
            json={"duration": "extra_long"},
        )
        assert res.status_code == 422

    def test_invalid_max_players(self, client):
        res = client.post(
            "/api/movie-night/room/create",
            json={"max_players": 1},
        )
        assert res.status_code == 422


class TestJoinRoom:
    def test_join_room(self, client, create_test_room):
        room_code, _ = create_test_room()
        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code, "player_name": "Alice"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["player_token"]) == 32
        assert data["session_state"] == "waiting"
        assert len(data["players"]) == 2  # host + Alice

    def test_join_nonexistent_room(self, client):
        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": "HERO-ZZZZ", "player_name": "Alice"},
        )
        assert res.status_code == 404

    def test_join_full_room(self, client, create_test_room):
        room_code, _ = create_test_room(max_players=2)
        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code, "player_name": "Alice"},
        )
        assert res.status_code == 200

        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code, "player_name": "Bob"},
        )
        assert res.status_code == 409

    def test_duplicate_name_gets_suffix(self, client, create_test_room):
        room_code, _ = create_test_room()
        # Host is "anonymous" (test env), try joining as "anonymous"
        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code, "player_name": "anonymous"},
        )
        assert res.status_code == 200
        data = res.json()
        names = [p["player_name"] for p in data["players"]]
        assert "anonymous" in names
        assert "anonymous2" in names

    def test_empty_name_rejected(self, client, create_test_room):
        room_code, _ = create_test_room()
        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code, "player_name": "   "},
        )
        assert res.status_code == 422

    def test_case_insensitive_room_code(self, client, create_test_room):
        room_code, _ = create_test_room()
        res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code.lower(), "player_name": "Alice"},
        )
        assert res.status_code == 200


class TestPollRoom:
    def test_poll_room(self, client, create_test_room):
        room_code, host_token = create_test_room()
        res = client.get(f"/api/movie-night/room/poll?token={host_token}")
        assert res.status_code == 200
        data = res.json()
        assert data["room_code"] == room_code
        assert data["state"] == "waiting"
        assert len(data["players"]) == 1

    def test_poll_invalid_token(self, client):
        res = client.get("/api/movie-night/room/poll?token=invalidtoken")
        assert res.status_code == 404

    def test_poll_expired_session(self, client, create_test_room):
        room_code, host_token = create_test_room()
        with session_scope() as db:
            session = db.query(MovieNightSession).filter(
                MovieNightSession.room_code == room_code,
            ).first()
            session.expires_at = datetime.utcnow() - timedelta(minutes=1)

        res = client.get(f"/api/movie-night/room/poll?token={host_token}")
        assert res.status_code == 200
        assert res.json()["state"] == "expired"


class TestSubmitVibes:
    def test_submit_vibes(self, client, create_test_room):
        room_code, host_token = create_test_room()
        join_res = client.post(
            "/api/movie-night/room/join",
            json={"room_code": room_code, "player_name": "Alice"},
        )
        guest_token = join_res.json()["player_token"]

        # Host submits vibes
        res = client.post(
            f"/api/movie-night/room/vibes?token={host_token}",
            json={"vibes": ["popcorn_night", "feel_good"]},
        )
        assert res.status_code == 200
        assert res.json()["state"] == "waiting"

        # Guest submits vibes → all submitted
        res = client.post(
            f"/api/movie-night/room/vibes?token={guest_token}",
            json={"vibes": ["mind_bending"]},
        )
        assert res.status_code == 200
        assert res.json()["state"] == "waiting"

    def test_submit_invalid_vibes(self, client, create_test_room):
        _, host_token = create_test_room()
        res = client.post(
            f"/api/movie-night/room/vibes?token={host_token}",
            json={"vibes": ["not_a_vibe"]},
        )
        assert res.status_code == 422

    def test_resubmit_vibes_allowed_during_waiting(self, client, create_test_room):
        _, host_token = create_test_room()

        # First submission
        client.post(f"/api/movie-night/room/vibes?token={host_token}", json={"vibes": ["popcorn_night"]})

        # Re-submitting during waiting is fine (lets players change their mind)
        res = client.post(
            f"/api/movie-night/room/vibes?token={host_token}",
            json={"vibes": ["feel_good"]},
        )
        assert res.status_code == 200


class TestCancelRoom:
    def test_cancel_room(self, client, create_test_room):
        room_code, host_token = create_test_room()
        res = client.delete(f"/api/movie-night/room/{room_code}")
        assert res.status_code == 204

        poll_res = client.get(f"/api/movie-night/room/poll?token={host_token}")
        assert poll_res.json()["state"] == "expired"
