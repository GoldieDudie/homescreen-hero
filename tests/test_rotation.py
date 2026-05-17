"""
Tests for rotation logic
"""
import pytest
from datetime import date
import random
from homescreen_hero.core.rotation import (
    _parse_month_day,
    _is_date_in_range,
    _group_is_active,
    _passes_gap_rule,
    _is_blacklisted,
    _get_ordered_groups,
    _select_collections_from_group,
    order_collections_for_display,
    run_rotation_with_history,
    run_auto_rotation_with_history,
)
from homescreen_hero.core.config.schema import (
    AppConfig,
    CollectionRef,
    CollectionGroupConfig,
    DateRange,
    PlexSettings,
    PlexLibraryConfig,
    RotationSettings,
)
from tests.conftest import cr


# Mock CollectionUsage for testing
class MockCollectionUsage:
    def __init__(self, collection_name, last_rotation_id):
        self.collection_name = collection_name
        self.last_rotation_id = last_rotation_id


class TestParseMonthDay:
    """Tests for _parse_month_day function"""

    def test_valid_date(self):
        month, day = _parse_month_day("12-25")
        assert month == 12
        assert day == 25

    def test_single_digit_month_day(self):
        month, day = _parse_month_day("1-5")
        assert month == 1
        assert day == 5

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid MM-DD date format"):
            _parse_month_day("invalid")

    def test_month_out_of_range(self):
        with pytest.raises(ValueError, match="Month out of range"):
            _parse_month_day("13-01")

    def test_day_out_of_range(self):
        with pytest.raises(ValueError, match="Day out of range"):
            _parse_month_day("12-32")


class TestIsDateInRange:
    """Tests for _is_date_in_range function"""

    def test_date_within_same_year_range(self):
        # December 1 to December 31
        dr = DateRange(start="12-01", end="12-31")
        assert _is_date_in_range(date(2024, 12, 15), dr) is True
        assert _is_date_in_range(date(2024, 12, 1), dr) is True
        assert _is_date_in_range(date(2024, 12, 31), dr) is True
        assert _is_date_in_range(date(2024, 11, 30), dr) is False
        assert _is_date_in_range(date(2024, 1, 1), dr) is False

    def test_date_wrapping_year_boundary(self):
        # November 20 to January 10 (wraps around year)
        dr = DateRange(start="11-20", end="01-10")
        assert _is_date_in_range(date(2024, 12, 15), dr) is True
        assert _is_date_in_range(date(2024, 11, 20), dr) is True
        assert _is_date_in_range(date(2024, 1, 10), dr) is True
        assert _is_date_in_range(date(2024, 11, 19), dr) is False
        assert _is_date_in_range(date(2024, 1, 11), dr) is False
        assert _is_date_in_range(date(2024, 6, 15), dr) is False


class TestGroupIsActive:
    """Tests for _group_is_active function"""

    def test_disabled_group(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=False,
            collections=[cr("Test Collection")]
        )
        assert _group_is_active(group, date(2024, 12, 15)) is False

    def test_enabled_group_no_date_range(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            collections=[cr("Test Collection")]
        )
        assert _group_is_active(group, date(2024, 12, 15)) is True

    def test_enabled_group_within_date_range(self):
        group = CollectionGroupConfig(
            name="Christmas",
            enabled=True,
            date_range=DateRange(start="12-01", end="12-26"),
            collections=[cr("Christmas Movies")]
        )
        assert _group_is_active(group, date(2024, 12, 15)) is True
        assert _group_is_active(group, date(2024, 12, 1)) is True
        assert _group_is_active(group, date(2024, 11, 30)) is False

    def test_enabled_group_outside_date_range(self):
        group = CollectionGroupConfig(
            name="Summer",
            enabled=True,
            date_range=DateRange(start="06-01", end="08-31"),
            collections=[cr("Summer Blockbusters")]
        )
        assert _group_is_active(group, date(2024, 7, 15)) is True
        assert _group_is_active(group, date(2024, 12, 15)) is False


class TestPassesGapRule:
    """Tests for _passes_gap_rule function"""

    def test_no_gap_requirement(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            min_gap_rotations=0,
            collections=[cr("Test Collection")]
        )
        ref = cr("Test Collection")
        usage_map = {
            ref: MockCollectionUsage("Test Collection", 5)
        }
        assert _passes_gap_rule(ref, group, max_rotation_id=6, usage_map=usage_map) is True

    def test_no_previous_rotations(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            min_gap_rotations=3,
            collections=[cr("Test Collection")]
        )
        assert _passes_gap_rule(cr("Test Collection"), group, max_rotation_id=0, usage_map={}) is True

    def test_never_used_before(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            min_gap_rotations=3,
            collections=[cr("New Collection")]
        )
        other_ref = cr("Other Collection")
        usage_map = {
            other_ref: MockCollectionUsage("Other Collection", 5)
        }
        assert _passes_gap_rule(cr("New Collection"), group, max_rotation_id=10, usage_map=usage_map) is True

    def test_gap_requirement_not_met(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            min_gap_rotations=5,
            collections=[cr("Test Collection")]
        )
        ref = cr("Test Collection")
        usage_map = {
            ref: MockCollectionUsage("Test Collection", 8)
        }
        # Current rotation is 10, last used at 8, gap is 2 (needs 5)
        assert _passes_gap_rule(ref, group, max_rotation_id=10, usage_map=usage_map) is False

    def test_gap_requirement_met(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            min_gap_rotations=5,
            collections=[cr("Test Collection")]
        )
        ref = cr("Test Collection")
        usage_map = {
            ref: MockCollectionUsage("Test Collection", 5)
        }
        # Current rotation is 11, last used at 5, gap is 6 (needs 5)
        assert _passes_gap_rule(ref, group, max_rotation_id=11, usage_map=usage_map) is True

    def test_gap_requirement_exactly_met(self):
        group = CollectionGroupConfig(
            name="Test",
            enabled=True,
            min_gap_rotations=3,
            collections=[cr("Test Collection")]
        )
        ref = cr("Test Collection")
        usage_map = {
            ref: MockCollectionUsage("Test Collection", 7)
        }
        # Current rotation is 10, last used at 7, gap is exactly 3
        assert _passes_gap_rule(ref, group, max_rotation_id=10, usage_map=usage_map) is True


class TestIsBlacklisted:
    """Tests for _is_blacklisted function"""

    def test_collection_not_blacklisted_empty_list(self):
        assert _is_blacklisted(cr("Collection A"), []) is False

    def test_collection_blacklisted(self):
        blacklist = ["Collection A", "Collection B"]
        assert _is_blacklisted(cr("Collection A"), blacklist) is True
        assert _is_blacklisted(cr("Collection B"), blacklist) is True

    def test_collection_not_in_blacklist(self):
        blacklist = ["Collection A", "Collection B"]
        assert _is_blacklisted(cr("Collection C"), blacklist) is False

    def test_case_sensitive_matching(self):
        blacklist = ["Collection A"]
        assert _is_blacklisted(cr("Collection A"), blacklist) is True
        assert _is_blacklisted(cr("collection a"), blacklist) is False
        assert _is_blacklisted(cr("COLLECTION A"), blacklist) is False

    def test_blacklist_is_name_only_ignores_library(self):
        # Blacklist matches by name across all libraries
        blacklist = ["Collection A"]
        assert _is_blacklisted(cr("Collection A", "Movies"), blacklist) is True
        assert _is_blacklisted(cr("Collection A", "TV Shows"), blacklist) is True


class TestGetOrderedGroups:
    """Tests for _get_ordered_groups function"""

    def test_display_order_sorts_by_display_order(self):
        """display_order group_order should sort groups by display_order"""
        groups = [
            CollectionGroupConfig(
                name="Group A",
                enabled=True,
                weight=5,
                display_order=2,
                collections=[cr("Collection A")]
            ),
            CollectionGroupConfig(
                name="Group B",
                enabled=True,
                weight=10,
                display_order=0,
                collections=[cr("Collection B")]
            ),
            CollectionGroupConfig(
                name="Group C",
                enabled=True,
                weight=1,
                display_order=1,
                collections=[cr("Collection C")]
            ),
        ]
        rng = random.Random(42)
        ordered = _get_ordered_groups(groups, "display_order", rng)

        # Should be sorted by display_order, not config order or weight
        assert ordered[0].name == "Group B"
        assert ordered[1].name == "Group C"
        assert ordered[2].name == "Group A"

    def test_weighted_strategy_sorts_by_weight(self):
        """Weighted strategy should sort groups by weight (descending)"""
        groups = [
            CollectionGroupConfig(
                name="Group A",
                enabled=True,
                weight=5,
                collections=[cr("Collection A")]
            ),
            CollectionGroupConfig(
                name="Group B",
                enabled=True,
                weight=10,
                collections=[cr("Collection B")]
            ),
            CollectionGroupConfig(
                name="Group C",
                enabled=True,
                weight=1,
                collections=[cr("Collection C")]
            ),
        ]
        rng = random.Random(42)
        ordered = _get_ordered_groups(groups, "weighted", rng)

        # Should be sorted by weight descending: B(10), A(5), C(1)
        assert ordered[0].name == "Group B"
        assert ordered[0].weight == 10
        assert ordered[1].name == "Group A"
        assert ordered[1].weight == 5
        assert ordered[2].name == "Group C"
        assert ordered[2].weight == 1

    def test_weighted_strategy_with_equal_weights(self):
        """Weighted strategy should preserve config order for groups with same weight"""
        groups = [
            CollectionGroupConfig(
                name="Group A",
                enabled=True,
                weight=5,
                collections=[cr("Collection A")]
            ),
            CollectionGroupConfig(
                name="Group B",
                enabled=True,
                weight=5,
                collections=[cr("Collection B")]
            ),
            CollectionGroupConfig(
                name="Group C",
                enabled=True,
                weight=5,
                collections=[cr("Collection C")]
            ),
        ]
        rng = random.Random(42)
        ordered = _get_ordered_groups(groups, "weighted", rng)

        # All have same weight, should preserve original order
        assert ordered[0].name == "Group A"
        assert ordered[1].name == "Group B"
        assert ordered[2].name == "Group C"

    def test_weighted_strategy_mixed_weights(self):
        """Weighted strategy with mixed weights including duplicates"""
        groups = [
            CollectionGroupConfig(
                name="Group A",
                enabled=True,
                weight=3,
                collections=[cr("Collection A")]
            ),
            CollectionGroupConfig(
                name="Group B",
                enabled=True,
                weight=10,
                collections=[cr("Collection B")]
            ),
            CollectionGroupConfig(
                name="Group C",
                enabled=True,
                weight=3,
                collections=[cr("Collection C")]
            ),
            CollectionGroupConfig(
                name="Group D",
                enabled=True,
                weight=7,
                collections=[cr("Collection D")]
            ),
        ]
        rng = random.Random(42)
        ordered = _get_ordered_groups(groups, "weighted", rng)

        # Should be: B(10), D(7), A(3), C(3) - A before C due to config order
        assert ordered[0].name == "Group B"
        assert ordered[1].name == "Group D"
        assert ordered[2].name == "Group A"
        assert ordered[3].name == "Group C"


class TestSelectCollectionsFromGroup:
    """Tests for _select_collections_from_group function"""

    def test_random_strategy_uses_random_sample(self):
        """Random strategy should use random sampling"""
        available = [cr("Collection A"), cr("Collection B"), cr("Collection C"), cr("Collection D")]
        usage_map = {}
        rng = random.Random(42)

        chosen = _select_collections_from_group(available, 2, "random", usage_map, rng)

        assert len(chosen) == 2
        assert all(c in available for c in chosen)

    def test_lru_strategy_prioritizes_never_used(self):
        """LRU strategy should prioritize collections never used"""
        ref_never = cr("Never Used")
        ref_recent = cr("Used Recently")
        ref_old = cr("Used Long Ago")
        available = [ref_never, ref_recent, ref_old]
        usage_map = {
            ref_recent: MockCollectionUsage("Used Recently", 10),
            ref_old: MockCollectionUsage("Used Long Ago", 5),
            # ref_never not in usage_map
        }
        rng = random.Random(42)

        chosen = _select_collections_from_group(available, 2, "lru", usage_map, rng)

        # Should pick "Never Used" first, then "Used Long Ago" (older rotation ID)
        assert chosen[0] == ref_never
        assert chosen[1] == ref_old

    def test_lru_strategy_orders_by_rotation_id(self):
        """LRU strategy should order by last_rotation_id ascending"""
        ref_r1 = cr("Recent 1")
        ref_o1 = cr("Old 1")
        ref_r2 = cr("Recent 2")
        ref_o2 = cr("Old 2")
        available = [ref_r1, ref_o1, ref_r2, ref_o2]
        usage_map = {
            ref_r1: MockCollectionUsage("Recent 1", 20),
            ref_o1: MockCollectionUsage("Old 1", 5),
            ref_r2: MockCollectionUsage("Recent 2", 15),
            ref_o2: MockCollectionUsage("Old 2", 8),
        }
        rng = random.Random(42)

        chosen = _select_collections_from_group(available, 3, "lru", usage_map, rng)

        # Should be ordered by rotation ID: Old 1 (5), Old 2 (8), Recent 2 (15)
        assert chosen == [ref_o1, ref_o2, ref_r2]

    def test_lru_strategy_all_never_used(self):
        """LRU strategy with all collections never used"""
        available = [cr("A"), cr("B"), cr("C"), cr("D")]
        usage_map = {}
        rng = random.Random(42)

        chosen = _select_collections_from_group(available, 2, "lru", usage_map, rng)

        # All have same priority (never used), should take first k from sorted
        assert len(chosen) == 2
        assert all(c in available for c in chosen)

    def test_lru_strategy_respects_k_parameter(self):
        """LRU strategy should respect the k parameter"""
        ref_a = cr("A")
        ref_b = cr("B")
        ref_c = cr("C")
        ref_d = cr("D")
        ref_e = cr("E")
        available = [ref_a, ref_b, ref_c, ref_d, ref_e]
        usage_map = {
            ref_a: MockCollectionUsage("A", 1),
            ref_b: MockCollectionUsage("B", 2),
            ref_c: MockCollectionUsage("C", 3),
            ref_d: MockCollectionUsage("D", 4),
            ref_e: MockCollectionUsage("E", 5),
        }
        rng = random.Random(42)

        # Request only 3 collections
        chosen = _select_collections_from_group(available, 3, "lru", usage_map, rng)

        # Should get oldest 3: A(1), B(2), C(3)
        assert chosen == [ref_a, ref_b, ref_c]


# Helper to create minimal AppConfig for testing
def _make_test_config(
    groups: list,
    max_collections: int = 10,
    per_library_limits: dict = None,
    group_order: str = "display_order",
    allow_repeats: bool = True,
    blacklisted_collections: list = None,
) -> AppConfig:
    return AppConfig(
        plex=PlexSettings(
            base_url="http://localhost:32400",
            token="test-token",
            libraries=[
                PlexLibraryConfig(name="Movies", enabled=True),
                PlexLibraryConfig(name="TV Shows", enabled=True),
            ],
        ),
        groups=groups,
        rotation=RotationSettings(
            enabled=True,
            max_collections=max_collections,
            group_order=group_order,
            allow_repeats=allow_repeats,
            blacklisted_collections=blacklisted_collections or [],
            per_library_limits=per_library_limits or {},
        ),
    )


class TestPerLibraryLimits:
    """Tests for per-library collection limits in rotation"""

    def test_library_limit_enforced_within_group(self):
        """Library limit should restrict selections even when group has more collections"""
        groups = [
            CollectionGroupConfig(
                name="Movies Group",
                enabled=True,
                min_picks=5,
                max_picks=5,
                collections=[
                    cr("Movie A", "Movies"),
                    cr("Movie B", "Movies"),
                    cr("Movie C", "Movies"),
                    cr("Movie D", "Movies"),
                    cr("Movie E", "Movies"),
                ],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
            per_library_limits={"Movies": 2},  # Only allow 2 from Movies
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # Should only select 2 despite group wanting 5
        assert len(result.selected_collections) == 2
        assert result.per_library_counts["Movies"] == 2

    def test_library_limits_across_multiple_groups(self):
        """Library limits should be enforced across multiple groups"""
        groups = [
            CollectionGroupConfig(
                name="Group 1",
                enabled=True,
                min_picks=2,
                max_picks=2,
                collections=[cr("Movie A", "Movies"), cr("Movie B", "Movies")],
            ),
            CollectionGroupConfig(
                name="Group 2",
                enabled=True,
                min_picks=2,
                max_picks=2,
                collections=[cr("Movie C", "Movies"), cr("Movie D", "Movies")],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
            per_library_limits={"Movies": 3},  # Only allow 3 total from Movies
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # Should select 3 total (2 from first group, 1 from second)
        assert len(result.selected_collections) == 3
        assert result.per_library_counts["Movies"] == 3

    def test_no_limit_for_library_allows_unlimited(self):
        """Collections from a library with no limit should be unrestricted"""
        groups = [
            CollectionGroupConfig(
                name="Mixed Group",
                enabled=True,
                min_picks=5,
                max_picks=5,
                collections=[
                    cr("Movie A", "Movies"),
                    cr("Movie B", "Movies"),
                    cr("TV A", "TV Shows"),
                    cr("TV B", "TV Shows"),
                    cr("TV C", "TV Shows"),
                ],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
            per_library_limits={"Movies": 1},  # Only limit Movies, not TV Shows
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # 1 Movie (limited) + 3 TV Shows (all available, no limit) = 4 total
        assert len(result.selected_collections) == 4
        assert result.per_library_counts["Movies"] == 1
        assert result.per_library_counts["TV Shows"] == 3

    def test_unknown_library_collections_allowed(self):
        """Collections from a library not in per_library_limits should be allowed"""
        groups = [
            CollectionGroupConfig(
                name="Mixed Group",
                enabled=True,
                min_picks=3,
                max_picks=3,
                collections=[
                    cr("Known Movie", "Movies"),
                    cr("Unknown Collection", "Other"),
                    cr("Another Unknown", "Other"),
                ],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
            per_library_limits={"Movies": 1},
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # Should select all 3 (1 Movie limited, 2 "Other" library allowed)
        assert len(result.selected_collections) == 3
        assert result.per_library_counts.get("Movies", 0) <= 1

    def test_empty_per_library_limits_allows_all(self):
        """Empty per_library_limits should not restrict any selections"""
        groups = [
            CollectionGroupConfig(
                name="Big Group",
                enabled=True,
                min_picks=5,
                max_picks=5,
                collections=[
                    cr("A", "Movies"),
                    cr("B", "Movies"),
                    cr("C", "Movies"),
                    cr("D", "Movies"),
                    cr("E", "Movies"),
                ],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
            per_library_limits={},  # No limits
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # Should select all 5 with no limits
        assert len(result.selected_collections) == 5

    def test_library_limit_zero_blocks_all(self):
        """A library limit of 0 should block all collections from that library"""
        groups = [
            CollectionGroupConfig(
                name="Movies Group",
                enabled=True,
                min_picks=3,
                max_picks=3,
                collections=[
                    cr("Movie A", "Movies"),
                    cr("Movie B", "Movies"),
                    cr("Movie C", "Movies"),
                ],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
            per_library_limits={"Movies": 0},  # Block all Movies
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # No collections should be selected
        assert len(result.selected_collections) == 0
        assert result.per_library_counts.get("Movies", 0) == 0

    def test_per_library_counts_tracked_in_result(self):
        """RotationResult should include per_library_counts"""
        groups = [
            CollectionGroupConfig(
                name="Mixed",
                enabled=True,
                min_picks=4,
                max_picks=4,
                collections=[
                    cr("Movie A", "Movies"),
                    cr("Movie B", "Movies"),
                    cr("TV A", "TV Shows"),
                    cr("TV B", "TV Shows"),
                ],
            ),
        ]
        config = _make_test_config(
            groups=groups,
            max_collections=10,
        )

        result = run_rotation_with_history(
            config,
            max_rotation_id=0,
            usage_map={},
            rng=random.Random(42),
        )

        # Result should track counts per library
        assert "Movies" in result.per_library_counts or "TV Shows" in result.per_library_counts
        total_tracked = sum(result.per_library_counts.values())
        assert total_tracked == 4


class TestAutoRotationPerLibraryLimits:
    """Tests for per-library limits in auto-rotation mode"""

    def test_auto_rotation_library_limit_enforced(self):
        """Auto-rotation should respect per-library limits"""
        all_collections = [
            cr("Movie A", "Movies"),
            cr("Movie B", "Movies"),
            cr("Movie C", "Movies"),
            cr("TV A", "TV Shows"),
            cr("TV B", "TV Shows"),
        ]

        result = run_auto_rotation_with_history(
            all_collections,
            max_collections=5,
            collection_selection="random",
            blacklisted_collections=[],
            allow_repeats=True,
            last_rotation_collections=[],
            max_rotation_id=0,
            usage_map={},
            per_library_limits={"Movies": 2, "TV Shows": 1},
            rng=random.Random(42),
        )

        # Should respect limits: max 2 Movies + max 1 TV Show = 3 total
        assert len(result.selected_collections) == 3
        assert result.per_library_counts.get("Movies", 0) <= 2
        assert result.per_library_counts.get("TV Shows", 0) <= 1

    def test_auto_rotation_no_limits(self):
        """Auto-rotation without limits should select up to max_collections"""
        all_collections = [cr(c, "Movies") for c in ["A", "B", "C", "D", "E"]]

        result = run_auto_rotation_with_history(
            all_collections,
            max_collections=5,
            collection_selection="random",
            blacklisted_collections=[],
            allow_repeats=True,
            last_rotation_collections=[],
            max_rotation_id=0,
            usage_map={},
            per_library_limits={},  # No limits
            rng=random.Random(42),
        )

        assert len(result.selected_collections) == 5

    def test_auto_rotation_iterative_selection(self):
        """Auto-rotation with limits should use iterative selection"""
        all_collections = [
            cr("M1", "Movies"), cr("M2", "Movies"), cr("M3", "Movies"), cr("M4", "Movies"),
            cr("T1", "TV Shows"), cr("T2", "TV Shows"),
        ]

        result = run_auto_rotation_with_history(
            all_collections,
            max_collections=4,
            collection_selection="random",
            blacklisted_collections=[],
            allow_repeats=True,
            last_rotation_collections=[],
            max_rotation_id=0,
            usage_map={},
            per_library_limits={"Movies": 2, "TV Shows": 2},
            rng=random.Random(42),
        )

        # Should select 4 total, respecting both limits
        assert len(result.selected_collections) == 4
        assert result.per_library_counts.get("Movies", 0) <= 2
        assert result.per_library_counts.get("TV Shows", 0) <= 2

    def test_auto_rotation_unknown_collections_allowed(self):
        """Auto-rotation should allow collections not limited by per_library_limits"""
        all_collections = [
            cr("Known", "Movies"),
            cr("Unknown1", "Other"),
            cr("Unknown2", "Other"),
        ]

        result = run_auto_rotation_with_history(
            all_collections,
            max_collections=3,
            collection_selection="random",
            blacklisted_collections=[],
            allow_repeats=True,
            last_rotation_collections=[],
            max_rotation_id=0,
            usage_map={},
            per_library_limits={"Movies": 1},
            rng=random.Random(42),
        )

        # Should select all 3 (1 from Movies, 2 from "Other" which has no limit)
        assert len(result.selected_collections) == 3


class TestOrderCollectionsForDisplay:
    """Tests for pin top/bottom positioning in display ordering."""

    def _config(self) -> AppConfig:
        return _make_test_config(groups=[])

    def test_pinned_top_comes_before_unpinned(self):
        config = self._config()
        top_pin = cr("Top Pin", "Movies")
        regular = cr("Regular", "Movies")
        result = order_collections_for_display(
            [regular, top_pin],
            config,
            pinned_names={top_pin},
            pinned_order={top_pin: 0},
            pinned_positions={top_pin: "top"},
            rng=random.Random(0),
        )
        assert result == [top_pin, regular]

    def test_pinned_bottom_comes_after_unpinned(self):
        config = self._config()
        bottom_pin = cr("Bottom Pin", "Movies")
        regular = cr("Regular", "Movies")
        result = order_collections_for_display(
            [bottom_pin, regular],
            config,
            pinned_names={bottom_pin},
            pinned_order={bottom_pin: 0},
            pinned_positions={bottom_pin: "bottom"},
            rng=random.Random(0),
        )
        assert result == [regular, bottom_pin]

    def test_top_and_bottom_pins_sandwich_regular(self):
        config = self._config()
        top_pin = cr("Top", "Movies")
        bottom_pin = cr("Bottom", "Movies")
        regular = cr("Middle", "Movies")
        result = order_collections_for_display(
            [bottom_pin, regular, top_pin],
            config,
            pinned_names={top_pin, bottom_pin},
            pinned_order={top_pin: 0, bottom_pin: 0},
            pinned_positions={top_pin: "top", bottom_pin: "bottom"},
            rng=random.Random(0),
        )
        assert result == [top_pin, regular, bottom_pin]

    def test_missing_position_defaults_to_top(self):
        # Back-compat: pins without a position entry should still go to top.
        config = self._config()
        pin = cr("Legacy Pin", "Movies")
        regular = cr("Regular", "Movies")
        result = order_collections_for_display(
            [regular, pin],
            config,
            pinned_names={pin},
            pinned_order={pin: 0},
            pinned_positions={},  # no entry → default "top"
            rng=random.Random(0),
        )
        assert result == [pin, regular]
