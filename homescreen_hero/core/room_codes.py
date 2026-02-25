import secrets

from homescreen_hero.core.db.base import session_scope
from homescreen_hero.core.db.models import MovieNightSession

# Exclude ambiguous characters: O, 0, I, 1, L
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4  # 31^4 = ~923,000 possible codes

ACTIVE_STATES = {"waiting", "voting"}


def generate_room_code(max_attempts: int = 10) -> str:
    # Generate a unique HERO-XXXX code, checking for collisions against active sessions.
    for _ in range(max_attempts):
        suffix = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        code = f"HERO-{suffix}"
        with session_scope() as db:
            existing = db.query(MovieNightSession).filter(
                MovieNightSession.room_code == code,
                MovieNightSession.state.in_(ACTIVE_STATES),
            ).first()
            if existing is None:
                return code
    raise RuntimeError("Failed to generate unique room code after max attempts")
