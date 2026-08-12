"""Quick validation of UpdateSettingsRequest schema."""
from pydantic import ValidationError
from qorder_api.api.admin_router import UpdateSettingsRequest, SettingsResponse

# Test 1: reject negative default_savory_minutes
try:
    UpdateSettingsRequest(default_savory_minutes=-1)
    print("FAIL: should reject negative savory_minutes")
except ValidationError:
    print("OK: rejects negative savory_minutes")

# Test 2: reject negative default_light_minutes
try:
    UpdateSettingsRequest(default_light_minutes=-1)
    print("FAIL: should reject negative light_minutes")
except ValidationError:
    print("OK: rejects negative light_minutes")

# Test 3: reject session_timeout_hours = 0
try:
    UpdateSettingsRequest(session_timeout_hours=0)
    print("FAIL: should reject session_timeout_hours=0")
except ValidationError:
    print("OK: rejects session_timeout_hours=0")

# Test 4: reject negative staff_call_cooldown_seconds
try:
    UpdateSettingsRequest(staff_call_cooldown_seconds=-5)
    print("FAIL: should reject negative cooldown")
except ValidationError:
    print("OK: rejects negative staff_call_cooldown_seconds")

# Test 5: accept valid values
r = UpdateSettingsRequest(
    default_savory_minutes=15,
    default_light_minutes=3,
    session_timeout_hours=8,
    staff_call_cooldown_seconds=30,
    currency="USD",
    report_sheet_id="abc123",
)
data = r.model_dump(exclude_unset=True)
print(f"OK: valid request with {len(data)} fields: {data}")

# Test 6: empty request is valid (no fields updated)
r2 = UpdateSettingsRequest()
assert r2.model_dump(exclude_unset=True) == {}
print("OK: empty request has no unset fields")

# Test 7: SettingsResponse has all expected fields
fields = set(SettingsResponse.model_fields.keys())
expected = {
    "kitchen_screen_requires_pin", "currency", "logo_url", "timezone",
    "default_savory_minutes", "default_light_minutes", "session_timeout_hours",
    "staff_call_cooldown_seconds", "report_sheet_id", "report_sync_cron",
    "bill_footer_note",
}
assert fields == expected, f"Mismatch: {fields ^ expected}"
print(f"OK: SettingsResponse has all {len(expected)} fields")

print("\nAll checks passed!")
