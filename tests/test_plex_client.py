import logging

from homescreen_hero.core.config.schema import (
    AppConfig,
    CollectionRef,
    PlexLibraryConfig,
    PlexSettings,
    RotationSettings,
)
from homescreen_hero.core.integrations import plex_client


class FakeHub:
    def __init__(self, section, title: str, fail_first_move: bool = False):
        self.section = section
        self.title = title
        self.identifier = title.replace(" ", "_")
        self.fail_first_move = fail_first_move
        self.move_calls = 0

    def move(self, after=None):
        self.move_calls += 1
        if self.fail_first_move and self.move_calls == 1:
            raise Exception("Simulated Plex API failure")

        hubs = self.section._hubs
        hubs.remove(self)
        if after is None:
            hubs.insert(0, self)
            return

        after_index = hubs.index(after)
        hubs.insert(after_index + 1, self)


class FakeSection:
    def __init__(self, name: str, titles: list[str], fail_first_move_for: set[str] | None = None):
        fail_first_move_for = fail_first_move_for or set()
        self.title = name
        self._hubs = [
            FakeHub(self, title, fail_first_move=title in fail_first_move_for)
            for title in titles
        ]

    def managedHubs(self):
        return list(self._hubs)


class FakeLibraryManager:
    def __init__(self, sections: dict[str, FakeSection]):
        self._sections = sections

    def section(self, name: str) -> FakeSection:
        return self._sections[name]


class FakeServer:
    def __init__(self, sections: dict[str, FakeSection]):
        self.library = FakeLibraryManager(sections)


def _make_config(*library_names: str) -> AppConfig:
    return AppConfig(
        plex=PlexSettings(
            base_url="http://localhost:32400",
            token="test-token",
            libraries=[PlexLibraryConfig(name=name, enabled=True) for name in library_names],
        ),
        rotation=RotationSettings(
            enabled=True,
            max_collections=10,
        ),
        groups=[],
    )


def _ref(name: str, library: str = "Movies") -> CollectionRef:
    return CollectionRef(library=library, name=name)


class FakeVisibility:
    def __init__(self, home: bool = False, shared: bool = False, recommended: bool = False):
        self.promotedToOwnHome = home
        self.promotedToSharedHome = shared
        self.promotedToRecommended = recommended
        self.update_calls: list[dict] = []

    def updateVisibility(self, home: bool, shared: bool, recommended: bool):
        self.update_calls.append({"home": home, "shared": shared, "recommended": recommended})
        self.promotedToOwnHome = home
        self.promotedToSharedHome = shared
        self.promotedToRecommended = recommended


def test_visibility_needs_update_returns_false_when_state_matches():
    # Regression: updateVisibility must NOT be called when state already matches.
    # Plex re-appends hubs to the end of the managed list on every updateVisibility call,
    # so calling it unnecessarily causes drift on every rotation.
    hub = FakeVisibility(home=True, shared=False, recommended=False)
    assert not plex_client._visibility_needs_update(hub, True, False, False)


def test_visibility_needs_update_returns_true_when_home_differs():
    hub = FakeVisibility(home=False, shared=False, recommended=False)
    assert plex_client._visibility_needs_update(hub, True, False, False)


def test_visibility_needs_update_returns_true_when_shared_differs():
    hub = FakeVisibility(home=True, shared=False, recommended=False)
    assert plex_client._visibility_needs_update(hub, True, True, False)


def test_visibility_needs_update_returns_true_when_recommended_differs():
    hub = FakeVisibility(home=False, shared=False, recommended=True)
    assert plex_client._visibility_needs_update(hub, False, False, False)


def test_visibility_needs_update_returns_false_when_all_false_matches():
    hub = FakeVisibility(home=False, shared=False, recommended=False)
    assert not plex_client._visibility_needs_update(hub, False, False, False)


class FakeManagedHubVisibility:
    # Mirrors plexapi ManagedHub: _promoted = "is in the Managed Recommendations
    # list" (separate from the three visibility flags). remove() deletes the entry.
    def __init__(self, identifier: str, *, promoted: bool = True,
                 home: bool = False, shared: bool = False, recommended: bool = False,
                 remove_raises: bool = False):
        self.identifier = identifier
        self._promoted = promoted
        self.promotedToOwnHome = home
        self.promotedToSharedHome = shared
        self.promotedToRecommended = recommended
        self.remove_raises = remove_raises
        self.removed = False
        self.update_calls: list[dict] = []

    def remove(self):
        if self.remove_raises:
            raise Exception("Simulated Plex remove failure")
        self.removed = True
        self._promoted = False

    def updateVisibility(self, home: bool, shared: bool, recommended: bool):
        self.update_calls.append({"home": home, "shared": shared, "recommended": recommended})
        self.promotedToOwnHome = home
        self.promotedToSharedHome = shared
        self.promotedToRecommended = recommended


def test_suppress_removes_lingering_custom_managed_hub():
    # Lingering entry: in the managed list (_promoted) with all flags False.
    # Must be removed, not left to accumulate.
    hub = FakeManagedHubVisibility("custom.collection.1.55497")
    assert plex_client._suppress_managed_hub(hub) == "removed"
    assert hub.removed
    assert hub.update_calls == []


def test_suppress_removes_promoted_custom_managed_hub():
    hub = FakeManagedHubVisibility("custom.collection.1.54910", recommended=True)
    assert plex_client._suppress_managed_hub(hub) == "removed"
    assert hub.removed


def test_suppress_leaves_system_hub_demotes_instead_of_removing():
    # Default system hubs (deletable in Plex but must never be removed) fall back
    # to a plain demote.
    hub = FakeManagedHubVisibility("movie.recentlyadded", recommended=True)
    assert plex_client._suppress_managed_hub(hub) == "demoted"
    assert not hub.removed
    assert hub.update_calls == [{"home": False, "shared": False, "recommended": False}]


def test_suppress_noop_when_not_a_managed_rec():
    # Never-promoted collection (not in managed list, flags already clear).
    hub = FakeManagedHubVisibility("custom.collection.1.99999", promoted=False)
    assert plex_client._suppress_managed_hub(hub) == "noop"
    assert not hub.removed
    assert hub.update_calls == []


def test_suppress_falls_back_to_demote_when_remove_fails():
    hub = FakeManagedHubVisibility("custom.collection.1.55497", recommended=True,
                                   remove_raises=True)
    assert plex_client._suppress_managed_hub(hub) == "demoted"
    assert not hub.removed
    assert hub.update_calls == [{"home": False, "shared": False, "recommended": False}]


# ---- same-title duplicate collections: canonical pick + stray suppression -----

class FakeCollection:
    def __init__(self, title: str, rating_key: int, *, child_count: int = 0,
                 recommended: bool = True):
        self.title = title
        self.ratingKey = rating_key
        self.childCount = child_count
        self._vis = FakeManagedHubVisibility(
            f"custom.collection.1.{rating_key}", recommended=recommended,
        )

    def visibility(self):
        return self._vis


class FakeCollSection:
    def __init__(self, collections: list):
        self._collections = collections

    def collections(self):
        return list(self._collections)


class FakeCollServer:
    def __init__(self, sections: dict):
        self.library = FakeLibraryManager(sections)


def test_canonical_collection_tiebreaks_on_lowest_rating_key_when_both_empty():
    # Both empty (e.g. between popular windows) → stable pick = original (lowest rk).
    old = FakeCollection("This Week Popular", 75158, child_count=0)
    new = FakeCollection("This Week Popular", 89117, child_count=0)
    assert plex_client._canonical_collection([new, old]) is old
    assert plex_client._canonical_collection([old, new]) is old


def test_canonical_collection_prefers_populated_over_empty():
    # The populated instance leads even if it's the NEWER ratingKey (mirror case:
    # manager migrated to a new collection, old one is an empty orphan).
    old_empty = FakeCollection("This Week Popular", 75158, child_count=0)
    new_full = FakeCollection("This Week Popular", 89117, child_count=3)
    assert plex_client._canonical_collection([old_empty, new_full]) is new_full
    # And the usual live case: original populated, stray empty → keep original.
    old_full = FakeCollection("This Week Popular", 75158, child_count=1)
    new_empty = FakeCollection("This Week Popular", 89117, child_count=0)
    assert plex_client._canonical_collection([new_empty, old_full]) is old_full


def test_get_library_collections_collapses_duplicate_titles_to_canonical():
    old = FakeCollection("This Week Popular", 75158)
    new = FakeCollection("This Week Popular", 89117)
    other = FakeCollection("Must See", 100)
    server = FakeCollServer({"DocuSeries": FakeCollSection([new, old, other])})
    result = plex_client.get_library_collections(server, "DocuSeries")
    # Duplicate collapses to the original, not the non-deterministic last-one-seen.
    assert result["This Week Popular"] is old
    assert result["Must See"] is other


def test_suppress_stray_duplicates_removes_stray_keeps_canonical():
    old = FakeCollection("This Week Popular", 75158)
    new = FakeCollection("This Week Popular", 89117)
    grouped = {"This Week Popular": [new, old]}
    n = plex_client._suppress_stray_duplicates(
        "DocuSeries", grouped,
        managed_names={"This Week Popular"},
        active_libraries={"DocuSeries"},
        dry_run=False,
    )
    assert n == 1
    assert new.visibility().removed          # stray dropped from managed recs
    assert not old.visibility().removed      # canonical (original) kept


def test_suppress_stray_duplicates_scoping():
    dup = {"Dup": [FakeCollection("Dup", 1), FakeCollection("Dup", 2)]}
    single = {"Solo": [FakeCollection("Solo", 5)]}
    # single instance → nothing to suppress
    assert plex_client._suppress_stray_duplicates("L", single, {"Solo"}, {"L"}, dry_run=False) == 0
    # title not managed → left alone
    assert plex_client._suppress_stray_duplicates("L", dup, set(), {"L"}, dry_run=False) == 0
    # library not active → left alone
    assert plex_client._suppress_stray_duplicates("L", dup, {"Dup"}, set(), dry_run=False) == 0


def test_suppress_stray_duplicates_dry_run_does_not_mutate():
    old = FakeCollection("Dup", 1)
    new = FakeCollection("Dup", 2)
    n = plex_client._suppress_stray_duplicates(
        "L", {"Dup": [old, new]}, {"Dup"}, {"L"}, dry_run=True,
    )
    assert n == 1                            # still reports the stray
    assert not new.visibility().removed      # but makes no Plex change


# ---- move_hub_after_verified: float-precision convergence recovery ----------

class ConvergenceFakeHub:
    # Simulates Plex's float-precision convergence: when `drifted` is set,
    # move() ignores the requested position and appends the hub to the end of
    # the list (Plex's "re-normalize" behaviour). A re-promote visibility cycle
    # (home False then True) restores clean float spacing so moves work again —
    # unless `recover_on_repromote` is False, modelling an unrecoverable hub.
    def __init__(self, section, title, *, promotable=True, drifted=False,
                 recover_on_repromote=True):
        self.section = section
        self.title = title
        self.identifier = title.replace(" ", "_")
        self.promotedToOwnHome = promotable
        self.promotedToSharedHome = False
        self.promotedToRecommended = False
        self.drifted = drifted
        self.recover_on_repromote = recover_on_repromote
        self.move_calls = 0
        self.visibility_cycles = 0

    def move(self, after=None):
        self.move_calls += 1
        hubs = self.section._hubs
        hubs.remove(self)
        if self.drifted:
            hubs.append(self)  # precision lost: lands at the end, not after anchor
            return
        if after is None:
            hubs.insert(0, self)
            return
        hubs.insert(hubs.index(after) + 1, self)

    def updateVisibility(self, home=None, shared=None, recommended=None):
        if home is not None:
            self.promotedToOwnHome = home
        if shared is not None:
            self.promotedToSharedHome = shared
        if recommended is not None:
            self.promotedToRecommended = recommended
        if home:  # the re-promote (on) half of the cycle
            self.visibility_cycles += 1
            if self.recover_on_repromote:
                self.drifted = False


class ConvergenceFakeSection:
    def __init__(self, name, hubs):
        self.title = name
        self.type = "movie"
        self._hubs = hubs
        for h in hubs:
            h.section = self

    def managedHubs(self):
        return list(self._hubs)


def _conv_server(monkeypatch, *hubs):
    # No real sleeping during the recovery visibility cycle.
    monkeypatch.setattr(plex_client.time, "sleep", lambda *_: None)
    section = ConvergenceFakeSection("Movies", list(hubs))
    return FakeServer({"Movies": section}), section


def test_verified_move_no_recovery_when_move_lands(monkeypatch):
    anchor = ConvergenceFakeHub(None, "Anchor")
    target = ConvergenceFakeHub(None, "Target")
    other = ConvergenceFakeHub(None, "Other")
    server, section = _conv_server(monkeypatch, anchor, other, target)

    err = plex_client.move_hub_after_verified(server, "Movies", "Target", "Anchor")

    assert err is None
    assert [h.title for h in section._hubs] == ["Anchor", "Target", "Other"]
    assert target.visibility_cycles == 0  # landed first try, no re-promote needed


def test_verified_move_recovers_via_repromote(monkeypatch):
    anchor = ConvergenceFakeHub(None, "Anchor")
    target = ConvergenceFakeHub(None, "Target", drifted=True)
    other = ConvergenceFakeHub(None, "Other")
    server, section = _conv_server(monkeypatch, anchor, other, target)

    err = plex_client.move_hub_after_verified(server, "Movies", "Target", "Anchor")

    assert err is None
    assert target.visibility_cycles == 1  # one re-promote cycle to recover
    assert [h.title for h in section._hubs] == ["Anchor", "Target", "Other"]


def test_verified_move_fails_when_hub_not_repromotable(monkeypatch):
    # Other sits between Anchor and Target so the drifted "append to end"
    # position differs from the correct "after Anchor" slot.
    anchor = ConvergenceFakeHub(None, "Anchor")
    other = ConvergenceFakeHub(None, "Other")
    target = ConvergenceFakeHub(None, "Target", promotable=False, drifted=True)
    server, section = _conv_server(monkeypatch, anchor, other, target)

    err = plex_client.move_hub_after_verified(server, "Movies", "Target", "Anchor")

    assert err is not None
    assert "not re-promotable" in err
    assert target.visibility_cycles == 0  # never attempted to re-promote


def test_verified_move_reports_precision_convergence_when_unrecoverable(monkeypatch):
    anchor = ConvergenceFakeHub(None, "Anchor")
    other = ConvergenceFakeHub(None, "Other")
    target = ConvergenceFakeHub(None, "Target", drifted=True, recover_on_repromote=False)
    server, section = _conv_server(monkeypatch, anchor, other, target)

    err = plex_client.move_hub_after_verified(server, "Movies", "Target", "Anchor")

    assert err is not None
    assert "precision convergence" in err
    assert target.visibility_cycles == 1  # tried to recover once, still failed


