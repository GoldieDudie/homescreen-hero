import pytest
from homescreen_hero.core.vibe_scoring import (
    compute_vibe_scores,
    VIBE_NAMES,
    SCORE_VERSION,
    VIBE_DISPLAY_NAMES,
    GENRE_VIBE_MAP,
    GENRE_COMBO_MODIFIERS,
    KEYWORD_VIBE_MAP,
    CONTENT_RATING_DAMPENERS,
    OVERVIEW_WEIGHT_FACTOR,
    OVERVIEW_MIN_TERM_LENGTH,
    OVERVIEW_SKIP_TERMS,
)


class TestVibeScoring:
    def test_empty_inputs_returns_all_zeros(self):
        scores = compute_vibe_scores([], [])
        assert all(scores[v] == 0.0 for v in VIBE_NAMES)

    def test_all_vibes_present_in_output(self):
        scores = compute_vibe_scores(["Action"], [])
        assert set(scores.keys()) == set(VIBE_NAMES)

    def test_scores_clamped_to_valid_range(self):
        # Use lots of genres and keywords to try to push scores above 1.0
        genres = ["Action", "Adventure", "Thriller", "Science Fiction"]
        keywords = [
            {"name": "superhero"},
            {"name": "blockbuster"},
            {"name": "epic"},
            {"name": "battle"},
            {"name": "quest"},
            {"name": "explosion"},
        ]
        scores = compute_vibe_scores(genres, keywords)
        for vibe, score in scores.items():
            assert 0.0 <= score <= 1.0, f"{vibe} score {score} out of range"

    def test_action_genre_scores_popcorn_night(self):
        scores = compute_vibe_scores(["Action"], [])
        assert scores["popcorn_night"] > 0.0
        assert scores["epic_adventure"] > 0.0

    def test_horror_genre_scores_nerve_wracking(self):
        scores = compute_vibe_scores(["Horror"], [])
        assert scores["nerve_wracking"] > 0.4
        assert scores["dark_twisted"] > 0.0

    def test_comedy_genre_scores_cheap_laughs(self):
        scores = compute_vibe_scores(["Comedy"], [])
        assert scores["cheap_laughs"] > 0.4
        assert scores["feel_good"] > 0.0

    def test_romance_genre_scores_hopeless_romantic(self):
        scores = compute_vibe_scores(["Romance"], [])
        assert scores["hopeless_romantic"] > 0.4

    def test_drama_genre_scores_gut_punch(self):
        scores = compute_vibe_scores(["Drama"], [])
        assert scores["gut_punch"] > 0.0

    def test_animation_genre_scores_kid_at_heart(self):
        scores = compute_vibe_scores(["Animation"], [])
        assert scores["kid_at_heart"] > 0.4

    def test_documentary_genre_scores_true_story(self):
        scores = compute_vibe_scores(["Documentary"], [])
        assert scores["true_story"] > 0.4

    def test_fantasy_genre_scores_epic_adventure(self):
        scores = compute_vibe_scores(["Fantasy"], [])
        assert scores["epic_adventure"] > 0.4

    def test_scifi_genre_scores_mind_bending(self):
        scores = compute_vibe_scores(["Science Fiction"], [])
        assert scores["mind_bending"] > 0.0

    def test_crime_genre_scores_dark_twisted(self):
        scores = compute_vibe_scores(["Crime"], [])
        assert scores["dark_twisted"] > 0.4

    def test_keywords_boost_scores(self):
        # Genre-only baseline
        genre_only = compute_vibe_scores(["Thriller"], [])
        # Genre + relevant keywords
        with_keywords = compute_vibe_scores(
            ["Thriller"],
            [{"name": "serial killer"}, {"name": "suspense"}],
        )
        assert with_keywords["nerve_wracking"] > genre_only["nerve_wracking"]

    def test_keyword_case_insensitive(self):
        scores = compute_vibe_scores([], [{"name": "Time Travel"}])
        assert scores["mind_bending"] > 0.0

    def test_keyword_missing_name_ignored(self):
        # Keywords without "name" key should be ignored
        scores = compute_vibe_scores(["Comedy"], [{"id": 123}])
        baseline = compute_vibe_scores(["Comedy"], [])
        assert scores == baseline

    def test_multi_genre_additive(self):
        # Multiple genres should accumulate scores
        single = compute_vibe_scores(["Action"], [])
        double = compute_vibe_scores(["Action", "Adventure"], [])
        assert double["epic_adventure"] > single["epic_adventure"]

    # ---------------------------------------------------------------
    # Genre combo modifier tests — verify that genre pairs shift the
    # vibe profile (e.g., Horror+Comedy is less scary, more funny)
    # ---------------------------------------------------------------

    def test_combo_horror_comedy_dampens_nerve_wracking(self):
        pure_horror = compute_vibe_scores(["Horror"], [])
        horror_comedy = compute_vibe_scores(["Horror", "Comedy"], [])
        # Comedy should dampen the scariness
        assert horror_comedy["nerve_wracking"] < pure_horror["nerve_wracking"]

    def test_combo_horror_comedy_boosts_cheap_laughs(self):
        pure_horror = compute_vibe_scores(["Horror"], [])
        horror_comedy = compute_vibe_scores(["Horror", "Comedy"], [])
        # Comedy combo should make it funnier than pure horror
        assert horror_comedy["cheap_laughs"] > pure_horror["cheap_laughs"]

    def test_combo_crime_comedy_dampens_dark_twisted(self):
        pure_crime = compute_vibe_scores(["Crime"], [])
        crime_comedy = compute_vibe_scores(["Crime", "Comedy"], [])
        assert crime_comedy["dark_twisted"] < pure_crime["dark_twisted"]

    def test_combo_romance_comedy_shifts_toward_fun(self):
        pure_romance = compute_vibe_scores(["Romance"], [])
        rom_com = compute_vibe_scores(["Romance", "Comedy"], [])
        # Rom-com should be lighter on the romance, more fun
        assert rom_com["hopeless_romantic"] < pure_romance["hopeless_romantic"]
        assert rom_com["feel_good"] > pure_romance["feel_good"]

    def test_combo_romance_drama_deepens_emotion(self):
        pure_romance = compute_vibe_scores(["Romance"], [])
        romance_drama = compute_vibe_scores(["Romance", "Drama"], [])
        # Romance+Drama should increase gut_punch
        assert romance_drama["gut_punch"] > pure_romance["gut_punch"]

    def test_combo_fantasy_horror_dampens_kid_at_heart(self):
        pure_fantasy = compute_vibe_scores(["Fantasy"], [])
        dark_fantasy = compute_vibe_scores(["Fantasy", "Horror"], [])
        # Dark fantasy should NOT feel kiddie
        assert dark_fantasy["kid_at_heart"] < pure_fantasy["kid_at_heart"]

    def test_combo_modifiers_dont_affect_single_genres(self):
        # A single genre that appears in combos should score the same
        # as if no combos existed (combos require 2+ matching genres)
        scores = compute_vibe_scores(["Horror"], [])
        assert scores["nerve_wracking"] == 0.6  # raw genre baseline, no modifier

    # ---------------------------------------------------------------
    # Content rating dampener tests
    # ---------------------------------------------------------------

    def test_g_rated_dampens_dark_vibes(self):
        no_rating = compute_vibe_scores(["Horror"], [])
        g_rated = compute_vibe_scores(["Horror"], [], content_rating="G")
        assert g_rated["nerve_wracking"] < no_rating["nerve_wracking"]
        assert g_rated["dark_twisted"] < no_rating["dark_twisted"]

    def test_r_rated_dampens_kid_at_heart(self):
        no_rating = compute_vibe_scores(["Animation", "Family"], [])
        r_rated = compute_vibe_scores(["Animation", "Family"], [], content_rating="R")
        assert r_rated["kid_at_heart"] < no_rating["kid_at_heart"]

    def test_g_rated_boosts_kid_at_heart(self):
        no_rating = compute_vibe_scores(["Animation"], [])
        g_rated = compute_vibe_scores(["Animation"], [], content_rating="G")
        assert g_rated["kid_at_heart"] > no_rating["kid_at_heart"]

    def test_no_content_rating_changes_nothing(self):
        without = compute_vibe_scores(["Action"], [])
        with_none = compute_vibe_scores(["Action"], [], content_rating=None)
        assert without == with_none

    def test_unknown_rating_changes_nothing(self):
        without = compute_vibe_scores(["Action"], [])
        with_unknown = compute_vibe_scores(["Action"], [], content_rating="UNKNOWN")
        assert without == with_unknown

    # ---------------------------------------------------------------
    # Substring keyword matching tests
    # ---------------------------------------------------------------

    def test_substring_match_finds_partial_keyword(self):
        # "female serial killer" should match our "serial killer" map entry
        exact = compute_vibe_scores([], [{"name": "serial killer"}])
        substring = compute_vibe_scores([], [{"name": "female serial killer"}])
        assert substring["nerve_wracking"] == exact["nerve_wracking"]
        assert substring["dark_twisted"] == exact["dark_twisted"]

    def test_substring_match_respects_word_boundaries(self):
        # "glove" should NOT match "love"
        with_love = compute_vibe_scores([], [{"name": "love"}])
        with_glove = compute_vibe_scores([], [{"name": "glove"}])
        assert with_love["hopeless_romantic"] > 0.0
        assert with_glove["hopeless_romantic"] == 0.0

    def test_substring_match_deduplicates(self):
        # Both "serial killer" and "female serial killer" in the same movie
        # should only count "serial killer" once
        single = compute_vibe_scores([], [{"name": "serial killer"}])
        both = compute_vibe_scores(
            [], [{"name": "serial killer"}, {"name": "female serial killer"}]
        )
        assert both["nerve_wracking"] == single["nerve_wracking"]

    def test_substring_match_multiple_keys_in_one_keyword(self):
        # "psychological serial killer thriller" could match both
        # "serial killer" and "psychological thriller"
        scores = compute_vibe_scores([], [{"name": "psychological serial killer thriller"}])
        assert scores["nerve_wracking"] > 0.0
        assert scores["dark_twisted"] > 0.0

    # ---------------------------------------------------------------
    # Keyword density weighting tests
    # ---------------------------------------------------------------

    def test_density_concentrated_keywords_score_higher(self):
        # 2 matching keywords out of 2 total = high density → full credit
        concentrated = compute_vibe_scores(
            [], [{"name": "serial killer"}, {"name": "suspense"}]
        )
        # Same 2 matching keywords buried among 20 unrelated ones → lower density
        diluted_keywords = [{"name": "serial killer"}, {"name": "suspense"}]
        for i in range(18):
            diluted_keywords.append({"name": f"unrelated keyword {i}"})
        diluted = compute_vibe_scores([], diluted_keywords)

        assert concentrated["nerve_wracking"] > diluted["nerve_wracking"]

    def test_density_no_keywords_no_penalty(self):
        # Zero keywords should produce same result as no keyword pass
        scores = compute_vibe_scores(["Action"], [])
        assert scores["popcorn_night"] == 0.5  # pure genre baseline

    def test_density_all_matching_gets_full_credit(self):
        # When all keywords match, density = 1.0, factor = 1.0
        # This means keyword boosts are applied at full strength
        all_match = compute_vibe_scores(
            [], [{"name": "serial killer"}, {"name": "suspense"}]
        )
        # Both keywords match, density = 2/2 = 1.0 → factor = 1.0
        # nerve_wracking should be 0.3 + 0.3 = 0.6 (full credit)
        assert all_match["nerve_wracking"] == 0.6

    # ---------------------------------------------------------------
    # Overview text scanning tests
    # ---------------------------------------------------------------

    def test_overview_boosts_scores_when_no_keywords(self):
        # Overview should add vibe signal even when there are no keywords
        no_overview = compute_vibe_scores(["Drama"], [])
        with_overview = compute_vibe_scores(
            ["Drama"], [],
            overview="A grieving mother struggles with terminal illness and tragedy.",
        )
        assert with_overview["gut_punch"] > no_overview["gut_punch"]

    def test_overview_does_not_double_count_keyword_matches(self):
        # If "serial killer" is already a keyword, the overview shouldn't add it again
        kw_only = compute_vibe_scores(
            [], [{"name": "serial killer"}],
            overview="A detective hunts a serial killer across the country.",
        )
        kw_no_overview = compute_vibe_scores(
            [], [{"name": "serial killer"}],
        )
        # Scores should be identical — overview match is deduplicated
        assert kw_only["nerve_wracking"] == kw_no_overview["nerve_wracking"]

    def test_overview_adds_new_terms_not_in_keywords(self):
        # "haunted house" in overview but not in keywords should boost nerve_wracking
        kw_only = compute_vibe_scores(
            ["Horror"], [{"name": "suspense"}],
        )
        kw_plus_overview = compute_vibe_scores(
            ["Horror"], [{"name": "suspense"}],
            overview="A family moves into a haunted house with a dark history.",
        )
        assert kw_plus_overview["nerve_wracking"] > kw_only["nerve_wracking"]

    def test_overview_applies_reduced_weight(self):
        # Overview-only match should be weaker than the same term as a keyword
        from_keyword = compute_vibe_scores(
            [], [{"name": "serial killer"}],
        )
        from_overview = compute_vibe_scores(
            [], [],
            overview="The story follows a serial killer terrorizing the city.",
        )
        # Overview weight is 0.4x of keyword weight
        assert from_overview["nerve_wracking"] > 0.0
        assert from_overview["nerve_wracking"] < from_keyword["nerve_wracking"]

    def test_overview_skips_short_terms(self):
        # "love" (4 chars) should be skipped in overview scanning
        no_overview = compute_vibe_scores([], [])
        with_overview = compute_vibe_scores(
            [], [],
            overview="A story about love and finding your soulmate.",
        )
        # "love" is < 5 chars so it's skipped, but "soulmate" (8 chars) should match
        assert with_overview["hopeless_romantic"] > no_overview["hopeless_romantic"]
        # Verify the boost is only from "soulmate", not "love" + "soulmate"
        soulmate_only = compute_vibe_scores(
            [], [],
            overview="Finding your soulmate across the world.",
        )
        assert with_overview["hopeless_romantic"] == soulmate_only["hopeless_romantic"]

    def test_overview_skips_excluded_terms(self):
        # "dream" is in OVERVIEW_SKIP_TERMS — shouldn't match in overview
        no_overview = compute_vibe_scores([], [])
        with_overview = compute_vibe_scores(
            [], [],
            overview="She had a dream about a mysterious world.",
        )
        assert with_overview["mind_bending"] == no_overview["mind_bending"]

    def test_overview_none_changes_nothing(self):
        without = compute_vibe_scores(["Action"], [])
        with_none = compute_vibe_scores(["Action"], [], overview=None)
        assert without == with_none

    def test_overview_empty_string_changes_nothing(self):
        without = compute_vibe_scores(["Action"], [])
        with_empty = compute_vibe_scores(["Action"], [], overview="")
        assert without == with_empty

    def test_overview_word_boundary_respected(self):
        # "survival" should match but "festival" should not trigger "stival" etc.
        scores = compute_vibe_scores(
            [], [],
            overview="A tale of survival in the wilderness.",
        )
        assert scores["nerve_wracking"] > 0.0

    # ---------------------------------------------------------------
    # "Movie profile" tests — verify well-known movie archetypes
    # score high on the expected vibes
    # ---------------------------------------------------------------

    def test_profile_horror_thriller(self):
        # e.g., The Shining, Get Out
        scores = compute_vibe_scores(
            ["Horror", "Thriller"],
            [{"name": "psychological thriller"}, {"name": "haunted house"}],
        )
        assert scores["nerve_wracking"] >= 0.8
        top_vibe = max(scores, key=scores.get)
        assert top_vibe == "nerve_wracking"

    def test_profile_scifi_mind_bender(self):
        # e.g., Inception, Arrival
        scores = compute_vibe_scores(
            ["Science Fiction", "Drama"],
            [{"name": "time travel"}, {"name": "twist ending"}],
        )
        assert scores["mind_bending"] >= 0.7

    def test_profile_romantic_comedy(self):
        # e.g., When Harry Met Sally, Crazy Rich Asians
        scores = compute_vibe_scores(
            ["Romance", "Comedy"],
            [{"name": "romantic comedy"}, {"name": "wedding"}],
        )
        assert scores["hopeless_romantic"] >= 0.7
        assert scores["cheap_laughs"] > 0.0

    def test_profile_war_drama(self):
        # e.g., Saving Private Ryan, Schindler's List
        scores = compute_vibe_scores(
            ["War", "Drama", "History"],
            [{"name": "world war ii"}, {"name": "based on true story"}],
        )
        assert scores["gut_punch"] >= 0.5
        assert scores["true_story"] >= 0.5

    def test_profile_animated_family(self):
        # e.g., Toy Story, Finding Nemo
        scores = compute_vibe_scores(
            ["Animation", "Family", "Comedy"],
            [{"name": "talking animal"}, {"name": "friendship"}],
        )
        assert scores["kid_at_heart"] >= 0.7
        assert scores["feel_good"] > 0.0

    def test_profile_crime_noir(self):
        # e.g., Se7en, No Country for Old Men
        scores = compute_vibe_scores(
            ["Crime", "Thriller"],
            [{"name": "serial killer"}, {"name": "neo-noir"}, {"name": "moral ambiguity"}],
        )
        assert scores["dark_twisted"] >= 0.7

    def test_profile_epic_fantasy(self):
        # e.g., Lord of the Rings
        scores = compute_vibe_scores(
            ["Fantasy", "Adventure", "Action"],
            [{"name": "quest"}, {"name": "battle"}, {"name": "epic"}, {"name": "sword and sorcery"}],
        )
        assert scores["epic_adventure"] >= 0.8

    def test_profile_feel_good(self):
        # e.g., The Pursuit of Happyness, Little Miss Sunshine
        scores = compute_vibe_scores(
            ["Drama", "Comedy"],
            [{"name": "underdog"}, {"name": "inspiring"}, {"name": "family"}],
        )
        assert scores["feel_good"] >= 0.5

    def test_profile_biopic(self):
        # e.g., The Social Network, Bohemian Rhapsody
        scores = compute_vibe_scores(
            ["Drama", "History"],
            [{"name": "biography"}, {"name": "based on true story"}],
        )
        assert scores["true_story"] >= 0.7

    def test_profile_blockbuster_action(self):
        # e.g., Marvel movie, Fast & Furious
        scores = compute_vibe_scores(
            ["Action", "Adventure"],
            [{"name": "superhero"}, {"name": "blockbuster"}, {"name": "sequel"}],
        )
        assert scores["popcorn_night"] >= 0.7

    def test_profile_horror_comedy(self):
        # e.g., Shaun of the Dead, Scary Movie
        scores = compute_vibe_scores(
            ["Horror", "Comedy"],
            [{"name": "parody"}, {"name": "zombie"}],
        )
        # Should be funny first, scary second
        assert scores["cheap_laughs"] > scores["nerve_wracking"]

    def test_profile_action_comedy(self):
        # e.g., Rush Hour, 21 Jump Street
        scores = compute_vibe_scores(
            ["Action", "Comedy"],
            [{"name": "buddy"}, {"name": "martial arts"}],
        )
        assert scores["cheap_laughs"] > 0.4
        assert scores["popcorn_night"] > 0.4


class TestVibeConstants:
    def test_vibe_names_count(self):
        assert len(VIBE_NAMES) == 11

    def test_display_names_match_vibe_names(self):
        assert set(VIBE_DISPLAY_NAMES.keys()) == set(VIBE_NAMES)

    def test_score_version_is_positive(self):
        assert SCORE_VERSION >= 1

    def test_genre_map_values_are_valid_vibes(self):
        for genre, vibes in GENRE_VIBE_MAP.items():
            for vibe_name in vibes:
                assert vibe_name in VIBE_NAMES, (
                    f"Genre '{genre}' references unknown vibe '{vibe_name}'"
                )

    def test_keyword_map_values_are_valid_vibes(self):
        for keyword, vibes in KEYWORD_VIBE_MAP.items():
            for vibe_name in vibes:
                assert vibe_name in VIBE_NAMES, (
                    f"Keyword '{keyword}' references unknown vibe '{vibe_name}'"
                )

    def test_genre_weights_in_valid_range(self):
        for genre, vibes in GENRE_VIBE_MAP.items():
            for vibe_name, weight in vibes.items():
                assert 0.0 < weight <= 1.0, (
                    f"Genre '{genre}' -> '{vibe_name}' weight {weight} out of range"
                )

    def test_keyword_weights_in_valid_range(self):
        for keyword, vibes in KEYWORD_VIBE_MAP.items():
            for vibe_name, weight in vibes.items():
                assert 0.0 < weight <= 1.0, (
                    f"Keyword '{keyword}' -> '{vibe_name}' weight {weight} out of range"
                )

    def test_combo_modifier_vibes_are_valid(self):
        for combo, modifiers in GENRE_COMBO_MODIFIERS.items():
            for vibe_name in modifiers:
                assert vibe_name in VIBE_NAMES, (
                    f"Combo {combo} references unknown vibe '{vibe_name}'"
                )

    def test_combo_modifier_genres_are_valid(self):
        valid_genres = set(GENRE_VIBE_MAP.keys())
        for combo in GENRE_COMBO_MODIFIERS:
            for genre in combo:
                assert genre in valid_genres, (
                    f"Combo references unknown genre '{genre}'"
                )

    def test_combo_modifier_values_are_reasonable(self):
        for combo, modifiers in GENRE_COMBO_MODIFIERS.items():
            for vibe_name, multiplier in modifiers.items():
                # Dampeners shouldn't go below 0.3, boosters shouldn't exceed 2.0
                assert 0.3 <= multiplier <= 2.0, (
                    f"Combo {combo} -> '{vibe_name}' multiplier {multiplier} out of range"
                )

    def test_content_rating_dampener_vibes_are_valid(self):
        for rating, dampeners in CONTENT_RATING_DAMPENERS.items():
            for vibe_name in dampeners:
                assert vibe_name in VIBE_NAMES, (
                    f"Rating '{rating}' references unknown vibe '{vibe_name}'"
                )

    def test_content_rating_dampener_values_are_reasonable(self):
        for rating, dampeners in CONTENT_RATING_DAMPENERS.items():
            for vibe_name, multiplier in dampeners.items():
                assert 0.1 <= multiplier <= 2.0, (
                    f"Rating '{rating}' -> '{vibe_name}' multiplier {multiplier} out of range"
                )

    def test_overview_weight_factor_in_range(self):
        assert 0.0 < OVERVIEW_WEIGHT_FACTOR <= 1.0

    def test_overview_min_term_length_is_positive(self):
        assert OVERVIEW_MIN_TERM_LENGTH >= 1

    def test_overview_skip_terms_are_in_keyword_map(self):
        # Every skip term should actually exist in KEYWORD_VIBE_MAP
        for term in OVERVIEW_SKIP_TERMS:
            assert term in KEYWORD_VIBE_MAP, (
                f"Skip term '{term}' not found in KEYWORD_VIBE_MAP"
            )
