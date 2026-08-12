"""Authentication & authorization: PIN/JWT utilities and role guards."""

from qorder_api.auth.dependencies import (
    CurrentUser,
    get_current_user,
    get_kitchen_pin_required,
    require_role,
)
from qorder_api.auth.jwt import (
    TokenError,
    TokenPayload,
    create_access_token,
    decode_access_token,
    decode_token,
)
from qorder_api.auth.passwords import (
    hash_password,
    hash_pin,
    verify_password,
    verify_pin,
)
from qorder_api.auth.ws_ticket import issue_ws_ticket, verify_ws_ticket

__all__ = [
    "CurrentUser",
    "TokenError",
    "TokenPayload",
    "create_access_token",
    "decode_access_token",
    "decode_token",
    "get_current_user",
    "get_kitchen_pin_required",
    "hash_password",
    "hash_pin",
    "issue_ws_ticket",
    "require_role",
    "verify_password",
    "verify_pin",
    "verify_ws_ticket",
]
