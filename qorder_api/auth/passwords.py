"""Password and PIN hashing utilities (R12.6).

Uses bcrypt for both admin passwords and staff PINs.
``passlib`` is not compatible with ``bcrypt>=4.1`` (drops ``__about__`` module),
so we call the ``bcrypt`` library directly — same algorithm, full compatibility.

All functions are synchronous — bcrypt is CPU-bound but acceptable for auth
endpoints that handle low-throughput credential verification.
"""

from __future__ import annotations

import bcrypt


# --- Admin passwords ---


def hash_password(plain: str) -> str:
    """Return a bcrypt hash for an admin password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# --- Staff PINs ---


def hash_pin(pin: str) -> str:
    """Return a bcrypt hash for a staff PIN."""
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, hashed: str) -> bool:
    """Verify a plain PIN against a bcrypt hash."""
    return bcrypt.checkpw(pin.encode(), hashed.encode())
