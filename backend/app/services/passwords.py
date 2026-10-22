"""Password hashing with argon2id (spec §6.4). Plain-text passwords never leave this module."""

from functools import lru_cache
from secrets import token_urlsafe

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# argon2-cffi defaults (RFC 9106 low-memory profile), pinned to the argon2id variant.
_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash(token_urlsafe(16))


def verify_password(password_hash: str | None, password: str) -> bool:
    """Check `password` against `password_hash`.

    With no hash (unknown email) a dummy hash is still verified, so the response time does not
    reveal whether an account exists.
    """
    try:
        return _hasher.verify(password_hash or _dummy_hash(), password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
