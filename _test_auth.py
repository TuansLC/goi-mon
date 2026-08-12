"""Quick smoke test for auth module."""
import uuid
from qorder_api.auth import (
    hash_password, verify_password,
    hash_pin, verify_pin,
    create_access_token, decode_token, TokenError,
)

# Test password hashing
h = hash_password("admin123")
assert verify_password("admin123", h), "password verify failed"
assert not verify_password("wrong", h), "password should not match"

# Test PIN hashing
ph = hash_pin("1234")
assert verify_pin("1234", ph), "pin verify failed"
assert not verify_pin("0000", ph), "pin should not match"

# Test JWT round-trip
uid = uuid.uuid4()
rid = uuid.uuid4()
token = create_access_token(user_id=uid, role="staff", restaurant_id=rid)
payload = decode_token(token)
assert payload["sub"] == str(uid)
assert payload["role"] == "staff"
assert payload["restaurant_id"] == str(rid)
assert "exp" in payload

# Test invalid token raises TokenError
try:
    decode_token("invalid.token.here")
    assert False, "should have raised"
except TokenError:
    pass

print("All auth smoke tests passed!")
