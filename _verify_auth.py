"""Quick smoke test for auth utilities."""
import uuid
from qorder_api.auth import (
    hash_password, verify_password,
    hash_pin, verify_pin,
    create_access_token, decode_token, TokenError,
)

# --- Password hashing ---
pw_hash = hash_password("SecurePass123!")
assert verify_password("SecurePass123!", pw_hash), "password verify failed"
assert not verify_password("wrong", pw_hash), "wrong password should fail"
print("[OK] password hash/verify")

# --- PIN hashing ---
pin_hash = hash_pin("1234")
assert verify_pin("1234", pin_hash), "pin verify failed"
assert not verify_pin("0000", pin_hash), "wrong pin should fail"
print("[OK] pin hash/verify")

# --- JWT round-trip ---
uid = uuid.uuid4()
rid = uuid.uuid4()
token = create_access_token(user_id=uid, role="admin", restaurant_id=rid)
payload = decode_token(token)
assert payload["sub"] == str(uid)
assert payload["role"] == "admin"
assert payload["restaurant_id"] == str(rid)
assert "exp" in payload
print("[OK] JWT create/decode round-trip")

# --- Invalid token ---
try:
    decode_token("invalid.token.here")
    assert False, "should have raised TokenError"
except TokenError:
    pass
print("[OK] TokenError on invalid token")

print("\nAll auth checks passed!")
