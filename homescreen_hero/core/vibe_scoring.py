from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional

# Bump this when the scoring algorithm changes to trigger recompute
SCORE_VERSION = 4

VIBE_NAMES = [
    "popcorn_night",
    "nerve_wracking",
    "mind_bending",
    "hopeless_romantic",
    "gut_punch",
    "epic_adventure",
    "cheap_laughs",
    "dark_twisted",
    "feel_good",
    "kid_at_heart",
    "true_story",
]

# Display names for each vibe (used by API responses / future UI)
VIBE_DISPLAY_NAMES = {
    "popcorn_night": "Popcorn Night",
    "nerve_wracking": "Nerve Wracking",
    "mind_bending": "Mind Bending",
    "hopeless_romantic": "Hopeless Romantic",
    "gut_punch": "Gut Punch",
    "epic_adventure": "Epic Adventure",
    "cheap_laughs": "Cheap Laughs",
    "dark_twisted": "Dark & Twisted",
    "feel_good": "Feel Good",
    "kid_at_heart": "Kid At Heart",
    "true_story": "True Story",
}

# ---------------------------------------------------------------------------
# Genre -> vibe baseline weights
# Each genre contributes a base score to relevant vibes.
# A single genre alone produces a moderate score (0.15-0.6).
# ---------------------------------------------------------------------------
GENRE_VIBE_MAP: Dict[str, Dict[str, float]] = {
    "Action": {
        "popcorn_night": 0.5,
        "epic_adventure": 0.15,
        "nerve_wracking": 0.15,
    },
    "Adventure": {
        "epic_adventure": 0.5,
        "popcorn_night": 0.4,
        "kid_at_heart": 0.15,
    },
    "Animation": {
        "kid_at_heart": 0.6,
        "feel_good": 0.2,
    },
    "Comedy": {
        "cheap_laughs": 0.5,
        "feel_good": 0.2,
        "popcorn_night": 0.15,
    },
    "Crime": {
        "dark_twisted": 0.5,
        "nerve_wracking": 0.3,
    },
    "Documentary": {
        "true_story": 0.6,
    },
    "Drama": {
        "gut_punch": 0.3,
    },
    "Family": {
        "kid_at_heart": 0.5,
        "feel_good": 0.3,
    },
    "Fantasy": {
        "epic_adventure": 0.5,
        "kid_at_heart": 0.15,
    },
    "History": {
        "true_story": 0.4,
        "gut_punch": 0.15,
    },
    "Horror": {
        "nerve_wracking": 0.6,
        "dark_twisted": 0.2,
    },
    "Music": {
        "feel_good": 0.3,
    },
    "Mystery": {
        "mind_bending": 0.3,
        "nerve_wracking": 0.3,
        "dark_twisted": 0.15,
    },
    "Romance": {
        "hopeless_romantic": 0.6,
        "feel_good": 0.15,
    },
    "Science Fiction": {
        "mind_bending": 0.4,
        "epic_adventure": 0.3,
    },
    "TV Movie": {
        "popcorn_night": 0.2,
    },
    "Thriller": {
        "nerve_wracking": 0.5,
        "dark_twisted": 0.2,
        "mind_bending": 0.15,
    },
    "War": {
        "gut_punch": 0.4,
        "true_story": 0.2,
        "epic_adventure": 0.15,
    },
    "Western": {
        "epic_adventure": 0.3,
        "dark_twisted": 0.2,
    },
}

# ---------------------------------------------------------------------------
# Genre combination modifiers
# When specific genre pairs appear together, they shift the vibe profile.
# Applied as multipliers AFTER the genre baseline pass.
# Uses subset matching: a Horror+Comedy+Action movie triggers both the
# Horror+Comedy and Action+Comedy modifiers (stacking is intentional).
# ---------------------------------------------------------------------------
GENRE_COMBO_MODIFIERS: Dict[FrozenSet[str], Dict[str, float]] = {
    # Comedy lightens darker/intense vibes
    frozenset({"Horror", "Comedy"}): {
        "nerve_wracking": 0.7,
        "cheap_laughs": 1.2,
    },
    frozenset({"Crime", "Comedy"}): {
        "dark_twisted": 0.7,
        "cheap_laughs": 1.2,
    },
    frozenset({"Thriller", "Comedy"}): {
        "nerve_wracking": 0.75,
        "cheap_laughs": 1.15,
    },
    frozenset({"Action", "Comedy"}): {
        "nerve_wracking": 0.75,
        "cheap_laughs": 1.2,
        "popcorn_night": 1.15,
        "epic_adventure": 0.5,
    },
    frozenset({"Romance", "Comedy"}): {
        "hopeless_romantic": 0.85,
        "cheap_laughs": 1.2,
        "feel_good": 1.15,
    },
    frozenset({"Drama", "Comedy"}): {
        "gut_punch": 0.8,
        "feel_good": 1.2,
    },
    # Drama deepens emotional weight
    frozenset({"Romance", "Drama"}): {
        "gut_punch": 1.2,
        "feel_good": 0.85,
    },
    # Fantasy crossovers
    frozenset({"Fantasy", "Horror"}): {
        "kid_at_heart": 0.5,
        "dark_twisted": 1.2,
    },
    # Animated action is less kiddie, more spectacle
    frozenset({"Animation", "Action"}): {
        "kid_at_heart": 0.8,
        "popcorn_night": 1.2,
    },
    # Sci-fi horror is cerebral + scary
    frozenset({"Science Fiction", "Horror"}): {
        "mind_bending": 1.2,
    },
    # True crime docs
    frozenset({"Documentary", "Crime"}): {
        "true_story": 1.15,
        "dark_twisted": 1.15,
    },
}

# ---------------------------------------------------------------------------
# TMDb keyword -> vibe boost weights
# Keywords are more specific than genres and add boost scores (0.1-0.35).
# Matched by lowercased keyword name.
# ---------------------------------------------------------------------------
KEYWORD_VIBE_MAP: Dict[str, Dict[str, float]] = {
    # --- POPCORN NIGHT ---
    "superhero": {"popcorn_night": 0.3, "epic_adventure": 0.2},
    "sequel": {"popcorn_night": 0.15},
    "blockbuster": {"popcorn_night": 0.3},
    "based on comic": {"popcorn_night": 0.2},
    "based on comic book": {"popcorn_night": 0.2},
    "reboot": {"popcorn_night": 0.2},
    "summer": {"popcorn_night": 0.1},
    "heist": {"popcorn_night": 0.2, "dark_twisted": 0.15},
    "car chase": {"popcorn_night": 0.2},
    "explosion": {"popcorn_night": 0.2},
    "martial arts": {"popcorn_night": 0.2},
    "spy": {"popcorn_night": 0.2, "nerve_wracking": 0.1},

    # --- NERVE WRACKING ---
    "serial killer": {"nerve_wracking": 0.3, "dark_twisted": 0.2},
    "slasher": {"nerve_wracking": 0.3},
    "survival": {"nerve_wracking": 0.25},
    "suspense": {"nerve_wracking": 0.3},
    "paranoia": {"nerve_wracking": 0.25, "mind_bending": 0.1},
    "stalker": {"nerve_wracking": 0.3},
    "haunting": {"nerve_wracking": 0.25},
    "haunted house": {"nerve_wracking": 0.3},
    "ghost": {"nerve_wracking": 0.2},
    "zombie": {"nerve_wracking": 0.25},
    "home invasion": {"nerve_wracking": 0.3},
    "psychological thriller": {"nerve_wracking": 0.3, "mind_bending": 0.15},
    "kidnapping": {"nerve_wracking": 0.25},
    "terror": {"nerve_wracking": 0.25},
    "monster": {"nerve_wracking": 0.2, "epic_adventure": 0.1},
    "vampire": {"nerve_wracking": 0.2, "dark_twisted": 0.15},
    "exorcism": {"nerve_wracking": 0.3},
    "possession": {"nerve_wracking": 0.25},
    "werewolf": {"nerve_wracking": 0.2},
    "supernatural": {"nerve_wracking": 0.2},
    "found footage": {"nerve_wracking": 0.25},

    # --- MIND BENDING ---
    "twist ending": {"mind_bending": 0.35},
    "time travel": {"mind_bending": 0.3},
    "time loop": {"mind_bending": 0.3},
    "dystopia": {"mind_bending": 0.2, "dark_twisted": 0.1},
    "alternate reality": {"mind_bending": 0.3},
    "simulation": {"mind_bending": 0.3},
    "dream": {"mind_bending": 0.25},
    "artificial intelligence": {"mind_bending": 0.25},
    "philosophical": {"mind_bending": 0.25},
    "surrealism": {"mind_bending": 0.3},
    "nonlinear timeline": {"mind_bending": 0.3},
    "parallel universe": {"mind_bending": 0.3},
    "space": {"mind_bending": 0.1, "epic_adventure": 0.2},
    "alien": {"mind_bending": 0.1, "epic_adventure": 0.15},
    "memory": {"mind_bending": 0.2},
    "puzzle": {"mind_bending": 0.25},
    "conspiracy": {"mind_bending": 0.2, "nerve_wracking": 0.1},
    "identity crisis": {"mind_bending": 0.2},
    "existentialism": {"mind_bending": 0.25},
    "cyberpunk": {"mind_bending": 0.2, "dark_twisted": 0.1},
    "virtual reality": {"mind_bending": 0.25},
    "multiverse": {"mind_bending": 0.3},
    "cerebral": {"mind_bending": 0.3},
    "cloning": {"mind_bending": 0.2},
    "robot": {"mind_bending": 0.15},

    # --- HOPELESS ROMANTIC ---
    "love": {"hopeless_romantic": 0.2},
    "love triangle": {"hopeless_romantic": 0.25},
    "forbidden love": {"hopeless_romantic": 0.3},
    "wedding": {"hopeless_romantic": 0.2, "feel_good": 0.1},
    "unrequited love": {"hopeless_romantic": 0.3, "gut_punch": 0.1},
    "soulmate": {"hopeless_romantic": 0.3},
    "first love": {"hopeless_romantic": 0.25, "feel_good": 0.1},
    "romantic comedy": {"hopeless_romantic": 0.2, "cheap_laughs": 0.15},
    "star-crossed lovers": {"hopeless_romantic": 0.3},
    "long-distance relationship": {"hopeless_romantic": 0.2},
    "proposal": {"hopeless_romantic": 0.2},
    "second chance": {"hopeless_romantic": 0.2},
    "opposites attract": {"hopeless_romantic": 0.15, "cheap_laughs": 0.1},
    "love letter": {"hopeless_romantic": 0.2},

    # --- GUT PUNCH ---
    "death": {"gut_punch": 0.2},
    "grief": {"gut_punch": 0.35},
    "loss": {"gut_punch": 0.3},
    "tragedy": {"gut_punch": 0.35},
    "terminal illness": {"gut_punch": 0.35},
    "addiction": {"gut_punch": 0.3, "dark_twisted": 0.1},
    "poverty": {"gut_punch": 0.25},
    "abuse": {"gut_punch": 0.3, "dark_twisted": 0.15},
    "depression": {"gut_punch": 0.3},
    "sacrifice": {"gut_punch": 0.25},
    "family drama": {"gut_punch": 0.2},
    "divorce": {"gut_punch": 0.2},
    "war veteran": {"gut_punch": 0.25, "true_story": 0.1},
    "holocaust": {"gut_punch": 0.35, "true_story": 0.2},
    "slavery": {"gut_punch": 0.3, "true_story": 0.2},
    "ptsd": {"gut_punch": 0.3},
    "orphan": {"gut_punch": 0.2},

    # --- EPIC ADVENTURE ---
    "epic": {"epic_adventure": 0.3},
    "sword and sorcery": {"epic_adventure": 0.3},
    "dragon": {"epic_adventure": 0.25, "kid_at_heart": 0.1},
    "wizard": {"epic_adventure": 0.2, "kid_at_heart": 0.1},
    "magic": {"epic_adventure": 0.2, "kid_at_heart": 0.15},
    "quest": {"epic_adventure": 0.25},
    "battle": {"epic_adventure": 0.25},
    "kingdom": {"epic_adventure": 0.2},
    "pirate": {"epic_adventure": 0.2, "popcorn_night": 0.15},
    "treasure": {"epic_adventure": 0.2},
    "mythology": {"epic_adventure": 0.25},
    "chosen one": {"epic_adventure": 0.2},
    "space opera": {"epic_adventure": 0.3, "mind_bending": 0.1},
    "dinosaur": {"epic_adventure": 0.25, "popcorn_night": 0.15},
    "world domination": {"epic_adventure": 0.2, "popcorn_night": 0.15},
    "sword fight": {"epic_adventure": 0.2},
    "exploration": {"epic_adventure": 0.2},
    "treasure hunt": {"epic_adventure": 0.2, "popcorn_night": 0.1},

    # --- CHEAP LAUGHS ---
    "slapstick": {"cheap_laughs": 0.35},
    "satire": {"cheap_laughs": 0.2, "mind_bending": 0.1},
    "parody": {"cheap_laughs": 0.35},
    "buddy": {"cheap_laughs": 0.25, "feel_good": 0.1},
    "buddy movie": {"cheap_laughs": 0.25},
    "road trip": {"cheap_laughs": 0.15, "feel_good": 0.15},
    "stoner": {"cheap_laughs": 0.3},
    "sex comedy": {"cheap_laughs": 0.3},
    "dark comedy": {"cheap_laughs": 0.2, "dark_twisted": 0.15},
    "mockumentary": {"cheap_laughs": 0.3},
    "stand-up comedy": {"cheap_laughs": 0.3},
    "prank": {"cheap_laughs": 0.25},
    "farce": {"cheap_laughs": 0.3},
    "bromance": {"cheap_laughs": 0.25, "feel_good": 0.1},
    "absurd humor": {"cheap_laughs": 0.3},
    "screwball comedy": {"cheap_laughs": 0.3},

    # --- DARK & TWISTED ---
    "neo-noir": {"dark_twisted": 0.35},
    "film noir": {"dark_twisted": 0.35},
    "mafia": {"dark_twisted": 0.3},
    "organized crime": {"dark_twisted": 0.3},
    "corruption": {"dark_twisted": 0.25},
    "revenge": {"dark_twisted": 0.25, "nerve_wracking": 0.1},
    "drug dealer": {"dark_twisted": 0.25},
    "drug cartel": {"dark_twisted": 0.3},
    "hitman": {"dark_twisted": 0.3},
    "psychopath": {"dark_twisted": 0.3, "nerve_wracking": 0.15},
    "antihero": {"dark_twisted": 0.25},
    "vigilante": {"dark_twisted": 0.2, "popcorn_night": 0.1},
    "prison": {"dark_twisted": 0.2},
    "death row": {"dark_twisted": 0.25, "gut_punch": 0.15},
    "torture": {"dark_twisted": 0.3, "nerve_wracking": 0.2},
    "moral ambiguity": {"dark_twisted": 0.25},
    "underworld": {"dark_twisted": 0.25},
    "gangster": {"dark_twisted": 0.3},
    "cannibalism": {"dark_twisted": 0.3, "nerve_wracking": 0.2},
    "cult": {"dark_twisted": 0.25, "nerve_wracking": 0.15},

    # --- FEEL GOOD ---
    "friendship": {"feel_good": 0.25},
    "underdog": {"feel_good": 0.3, "popcorn_night": 0.1},
    "redemption": {"feel_good": 0.25, "gut_punch": 0.1},
    "christmas": {"feel_good": 0.25, "kid_at_heart": 0.1},
    "holiday": {"feel_good": 0.2},
    "inspiring": {"feel_good": 0.3},
    "feel-good": {"feel_good": 0.35},
    "heartwarming": {"feel_good": 0.35},
    "dog": {"feel_good": 0.15},
    "community": {"feel_good": 0.2},
    "sports": {"feel_good": 0.15, "popcorn_night": 0.1},
    "dance": {"feel_good": 0.2},
    "cooking": {"feel_good": 0.2},
    "small town": {"feel_good": 0.15},
    "kindness": {"feel_good": 0.25},
    "family": {"feel_good": 0.2},
    "coming of age": {"feel_good": 0.15, "kid_at_heart": 0.1},
    "mentor": {"feel_good": 0.15},
    "road trip": {"feel_good": 0.15, "cheap_laughs": 0.15},
    "music": {"feel_good": 0.15},

    # --- KID AT HEART ---
    "fairy tale": {"kid_at_heart": 0.3, "feel_good": 0.1},
    "talking animal": {"kid_at_heart": 0.3},
    "toy": {"kid_at_heart": 0.3},
    "princess": {"kid_at_heart": 0.25},
    "nostalgia": {"kid_at_heart": 0.25},
    "school": {"kid_at_heart": 0.15},
    "childhood": {"kid_at_heart": 0.25},
    "imaginary friend": {"kid_at_heart": 0.3},
    "theme park": {"kid_at_heart": 0.2},
    "musical": {"kid_at_heart": 0.15, "feel_good": 0.15},
    "cartoon": {"kid_at_heart": 0.3},
    "superhero": {"kid_at_heart": 0.1},
    "lego": {"kid_at_heart": 0.3},
    "pixar": {"kid_at_heart": 0.3, "feel_good": 0.15},

    # --- TRUE STORY ---
    "based on true story": {"true_story": 0.35},
    "biography": {"true_story": 0.35},
    "biopic": {"true_story": 0.35},
    "historical event": {"true_story": 0.3},
    "inspired by true events": {"true_story": 0.3},
    "political": {"true_story": 0.15},
    "court case": {"true_story": 0.2},
    "journalism": {"true_story": 0.25},
    "whistleblower": {"true_story": 0.25, "gut_punch": 0.1},
    "nasa": {"true_story": 0.2, "epic_adventure": 0.1},
    "world war ii": {"true_story": 0.25, "gut_punch": 0.15},
    "world war i": {"true_story": 0.25, "gut_punch": 0.15},
    "civil rights": {"true_story": 0.25, "gut_punch": 0.2},
    "cold war": {"true_story": 0.2, "nerve_wracking": 0.1},
    "true crime": {"true_story": 0.3, "dark_twisted": 0.15},
    "historical fiction": {"true_story": 0.15},
}


# ---------------------------------------------------------------------------
# Content rating dampeners
# MPAA ratings provide a strong signal for certain vibes. G/PG movies are
# unlikely to be dark or scary; R/NC-17 movies are unlikely to be kiddie.
# Applied as multipliers AFTER all additive scoring is done, BEFORE clamping.
# ---------------------------------------------------------------------------
CONTENT_RATING_DAMPENERS: Dict[str, Dict[str, float]] = {
    "G": {
        "nerve_wracking": 0.3,
        "dark_twisted": 0.2,
        "gut_punch": 0.5,
        "kid_at_heart": 1.15,
        "feel_good": 1.1,
    },
    "PG": {
        "nerve_wracking": 0.5,
        "dark_twisted": 0.4,
        "gut_punch": 0.7,
        "kid_at_heart": 1.1,
    },
    "PG-13": {
        "kid_at_heart": 0.85,
    },
    "R": {
        "kid_at_heart": 0.4,
    },
    "NC-17": {
        "kid_at_heart": 0.2,
        "feel_good": 0.7,
    },
}


# ---------------------------------------------------------------------------
# Overview text scanning
# When TMDb provides a plot summary, we scan it for the same terms used in
# KEYWORD_VIBE_MAP. Boosts are applied at reduced weight since a keyword
# mentioned in a plot synopsis is a weaker signal than a structured TMDb tag.
# Only terms NOT already matched by the keyword pass get counted (no double-
# counting). Short/common words are skipped to reduce false positives.
# ---------------------------------------------------------------------------
OVERVIEW_WEIGHT_FACTOR = 0.4
OVERVIEW_MIN_TERM_LENGTH = 5

# Terms to skip during overview scanning even if they meet the length minimum.
# These appear too frequently in plot text to be reliable vibe signals.
OVERVIEW_SKIP_TERMS = frozenset({
    "dream", "music", "dance", "space", "family", "school",
    "buddy", "mentor", "sports", "sequel", "reboot", "summer",
    "blockbuster", "memory", "quest", "magic", "robot", "alien",
    "ghost", "prank", "farce",
})


def _is_word_boundary_match(map_key: str, keyword: str) -> bool:
    # Check if map_key appears as whole words within keyword.
    # Prevents "love" matching "glove" while allowing "serial killer"
    # to match "female serial killer".
    idx = keyword.find(map_key)
    if idx == -1:
        return False
    # Left boundary: start of string or non-alphanumeric character
    if idx > 0 and keyword[idx - 1].isalnum():
        return False
    # Right boundary: end of string or non-alphanumeric character
    end = idx + len(map_key)
    if end < len(keyword) and keyword[end].isalnum():
        return False
    return True


def _find_keyword_matches(keyword_names: set) -> set:
    # Find all KEYWORD_VIBE_MAP keys that match the movie's keywords,
    # using exact match first, then word-boundary substring matching.
    # Returns a deduplicated set of matched map keys.
    matched_map_keys: set = set()
    for kw_name in keyword_names:
        # Exact match (fast path)
        if kw_name in KEYWORD_VIBE_MAP:
            matched_map_keys.add(kw_name)
        # Substring match: check if any map key appears as whole words
        # within this movie keyword (e.g., "female serial killer" → "serial killer")
        for map_key in KEYWORD_VIBE_MAP:
            if len(map_key) < len(kw_name) and _is_word_boundary_match(map_key, kw_name):
                matched_map_keys.add(map_key)
    return matched_map_keys


def _scan_overview_matches(overview: str, already_matched: set) -> set:
    # Scan plot summary text for KEYWORD_VIBE_MAP keys not already matched
    # by the keyword pass. Skips short/common terms to reduce noise.
    overview_lower = overview.lower()
    found: set = set()
    for map_key in KEYWORD_VIBE_MAP:
        if map_key in already_matched:
            continue
        if len(map_key) < OVERVIEW_MIN_TERM_LENGTH:
            continue
        if map_key in OVERVIEW_SKIP_TERMS:
            continue
        if _is_word_boundary_match(map_key, overview_lower):
            found.add(map_key)
    return found


def compute_vibe_scores(
    genres: List[str],
    keywords: List[Dict[str, Any]],
    content_rating: Optional[str] = None,
    overview: Optional[str] = None,
) -> Dict[str, float]:
    # Compute vibe scores from genres, TMDb keywords, content rating, and overview.
    # Pipeline: genre baselines → combo modifiers → keyword boosts →
    #           overview text boosts → content rating dampeners → clamp [0.0, 1.0].
    scores = {vibe: 0.0 for vibe in VIBE_NAMES}

    # Pass 1: Genre baseline (additive)
    for genre in genres:
        genre_contributions = GENRE_VIBE_MAP.get(genre, {})
        for vibe, weight in genre_contributions.items():
            scores[vibe] += weight

    # Pass 2: Genre combo modifiers (multiplicative)
    genre_set = set(genres)
    for combo, modifiers in GENRE_COMBO_MODIFIERS.items():
        if combo.issubset(genre_set):
            for vibe, multiplier in modifiers.items():
                scores[vibe] *= multiplier

    # Pass 3: Keyword boosts (additive, with substring matching + density weighting)
    keyword_names = {kw["name"].lower() for kw in keywords if "name" in kw}
    total_keywords = len(keyword_names)
    matched_map_keys = _find_keyword_matches(keyword_names)

    # Accumulate keyword boosts separately so we can apply density weighting
    keyword_boosts = {vibe: 0.0 for vibe in VIBE_NAMES}
    for map_key in matched_map_keys:
        for vibe, weight in KEYWORD_VIBE_MAP[map_key].items():
            keyword_boosts[vibe] += weight

    # Density weighting: when a small fraction of a movie's keywords match
    # our map, the signal is weaker (likely incidental rather than thematic).
    # Full credit when >= 1/3 of keywords match; soft reduction below that.
    # Range: [0.6, 1.0] — never reduces by more than 40%.
    if total_keywords > 0 and matched_map_keys:
        density = len(matched_map_keys) / total_keywords
        density_factor = min(1.0, 0.6 + 0.4 * min(1.0, density * 3))
        for vibe in keyword_boosts:
            keyword_boosts[vibe] *= density_factor

    for vibe in scores:
        scores[vibe] += keyword_boosts[vibe]

    # Pass 4: Overview text boosts (additive, reduced weight)
    # Scan the plot summary for vibe terms not already caught by keywords.
    if overview:
        overview_matches = _scan_overview_matches(overview, matched_map_keys)
        for map_key in overview_matches:
            for vibe, weight in KEYWORD_VIBE_MAP[map_key].items():
                scores[vibe] += weight * OVERVIEW_WEIGHT_FACTOR

    # Pass 5: Content rating dampeners (multiplicative)
    if content_rating:
        dampeners = CONTENT_RATING_DAMPENERS.get(content_rating, {})
        for vibe, multiplier in dampeners.items():
            scores[vibe] *= multiplier

    # Clamp to [0.0, 1.0]
    for vibe in scores:
        scores[vibe] = round(min(1.0, max(0.0, scores[vibe])), 4)

    return scores
