import pytest
from pydantic import ValidationError

from homescreen_hero.web.routers.movie_night import (
    MovieNightPickRequest,
    PlayerSelection,
    MovieNightGroupPickRequest,
    _merge_duration_filters,
    _merge_rewatch_modes,
)


# --- Single-player schema validation ---


class TestMovieNightPickRequest:
    def test_single_vibe_allowed(self):
        req = MovieNightPickRequest(vibes=["popcorn_night"])
        assert req.vibes == ["popcorn_night"]

    def test_many_vibes_allowed(self):
        req = MovieNightPickRequest(
            vibes=["popcorn_night", "mind_bending", "feel_good", "cheap_laughs", "gut_punch"]
        )
        assert len(req.vibes) == 5

    def test_zero_vibes_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            MovieNightPickRequest(vibes=[])

    def test_unknown_vibe_rejected(self):
        with pytest.raises(ValidationError, match="Unknown vibe"):
            MovieNightPickRequest(vibes=["not_a_vibe"])

    def test_invalid_duration_rejected(self):
        with pytest.raises(ValidationError, match="Invalid duration"):
            MovieNightPickRequest(vibes=["popcorn_night"], duration="extra_long")

    def test_invalid_rewatch_mode_rejected(self):
        with pytest.raises(ValidationError, match="Invalid rewatch_mode"):
            MovieNightPickRequest(vibes=["popcorn_night"], rewatch_mode="maybe")


# --- Group schema validation ---


class TestGroupPickRequest:
    def test_two_players_valid(self):
        req = MovieNightGroupPickRequest(
            players=[
                PlayerSelection(vibes=["mind_bending"]),
                PlayerSelection(vibes=["feel_good"]),
            ]
        )
        assert len(req.players) == 2

    def test_three_players_valid(self):
        req = MovieNightGroupPickRequest(
            players=[
                PlayerSelection(vibes=["mind_bending"]),
                PlayerSelection(vibes=["feel_good"]),
                PlayerSelection(vibes=["cheap_laughs"]),
            ]
        )
        assert len(req.players) == 3

    def test_single_player_rejected(self):
        with pytest.raises(ValidationError, match="at least 2"):
            MovieNightGroupPickRequest(
                players=[PlayerSelection(vibes=["mind_bending"])]
            )

    def test_empty_players_rejected(self):
        with pytest.raises(ValidationError, match="at least 2"):
            MovieNightGroupPickRequest(players=[])

    def test_player_with_zero_vibes_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            MovieNightGroupPickRequest(
                players=[
                    PlayerSelection(vibes=[]),
                    PlayerSelection(vibes=["feel_good"]),
                ]
            )

    def test_player_defaults(self):
        p = PlayerSelection(vibes=["popcorn_night"])
        assert p.duration is None
        assert p.rewatch_mode == "any"


# --- Duration filter merging ---


class TestMergeDurationFilters:
    def test_both_same(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration="quick"),
            PlayerSelection(vibes=["mind_bending"], duration="quick"),
        ]
        assert _merge_duration_filters(players) == "quick"

    def test_one_any_one_specific(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration=None),
            PlayerSelection(vibes=["mind_bending"], duration="long"),
        ]
        assert _merge_duration_filters(players) == "long"

    def test_both_any(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration=None),
            PlayerSelection(vibes=["mind_bending"], duration=None),
        ]
        assert _merge_duration_filters(players) is None

    def test_conflict_drops_filter(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration="quick"),
            PlayerSelection(vibes=["mind_bending"], duration="long"),
        ]
        assert _merge_duration_filters(players) is None

    def test_three_players_all_same(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration="standard"),
            PlayerSelection(vibes=["mind_bending"], duration="standard"),
            PlayerSelection(vibes=["feel_good"], duration="standard"),
        ]
        assert _merge_duration_filters(players) == "standard"

    def test_three_players_two_agree_one_any(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration="quick"),
            PlayerSelection(vibes=["mind_bending"], duration=None),
            PlayerSelection(vibes=["feel_good"], duration="quick"),
        ]
        assert _merge_duration_filters(players) == "quick"

    def test_three_players_conflict(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], duration="quick"),
            PlayerSelection(vibes=["mind_bending"], duration="long"),
            PlayerSelection(vibes=["feel_good"], duration="standard"),
        ]
        assert _merge_duration_filters(players) is None


# --- Rewatch mode merging ---
# Note: these tests mock _get_user_watched_keys to avoid Plex calls.


class TestMergeRewatchModes:
    def test_both_any_no_filter(self):
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="any"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="any"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "any"
        assert exclude is None
        assert only is None
        assert fallback is None

    def test_new_overrides_any(self, monkeypatch):
        monkeypatch.setattr(
            "homescreen_hero.web.routers.movie_night._get_user_watched_keys",
            lambda u: {1, 2, 3},
        )
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="new"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="any"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "new"
        assert exclude == {1, 2, 3}
        assert only is None

    def test_new_overrides_rewatch(self, monkeypatch):
        monkeypatch.setattr(
            "homescreen_hero.web.routers.movie_night._get_user_watched_keys",
            lambda u: {1, 2, 3},
        )
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="new"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="rewatch"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "new"
        assert exclude == {1, 2, 3}

    def test_rewatch_when_all_agree(self, monkeypatch):
        monkeypatch.setattr(
            "homescreen_hero.web.routers.movie_night._get_user_watched_keys",
            lambda u: {10, 20},
        )
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="rewatch"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="rewatch"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "rewatch"
        assert only == {10, 20}
        assert exclude is None

    def test_rewatch_plus_any_uses_rewatch(self, monkeypatch):
        monkeypatch.setattr(
            "homescreen_hero.web.routers.movie_night._get_user_watched_keys",
            lambda u: {10, 20},
        )
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="rewatch"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="any"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "rewatch"
        assert only == {10, 20}

    def test_plex_unavailable_degrades(self, monkeypatch):
        monkeypatch.setattr(
            "homescreen_hero.web.routers.movie_night._get_user_watched_keys",
            lambda u: None,
        )
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="new"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="any"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "any"
        assert fallback == "plex_unavailable"

    def test_three_players_new_wins(self, monkeypatch):
        monkeypatch.setattr(
            "homescreen_hero.web.routers.movie_night._get_user_watched_keys",
            lambda u: {5},
        )
        players = [
            PlayerSelection(vibes=["popcorn_night"], rewatch_mode="any"),
            PlayerSelection(vibes=["mind_bending"], rewatch_mode="rewatch"),
            PlayerSelection(vibes=["feel_good"], rewatch_mode="new"),
        ]
        mode, exclude, only, fallback = _merge_rewatch_modes(players, "testuser")
        assert mode == "new"
        assert exclude == {5}
