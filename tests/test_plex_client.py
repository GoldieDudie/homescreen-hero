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


