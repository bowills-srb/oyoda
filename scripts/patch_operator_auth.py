#!/usr/bin/env python3
"""
patch_operator_auth.py — Moves operator credentials to Railway env vars.

After running this, set in Railway:
  OPERATOR_1_EMAIL    = owner@theiremail.com
  OPERATOR_1_PASSWORD = TheirSecurePassword123!
  OPERATOR_1_ID       = OPERATOR_UUID (from pre_booking_setup.py)
  OPERATOR_1_NAME     = Owner Name
  OPERATOR_1_COMPANY  = Their Company Name

Run from ~/Downloads/oyvoda/:
  python3 scripts/patch_operator_auth.py
"""

path = "app/api/v1/endpoints/operator_app.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = '''    # Demo credentials for first operator \u2014 in production this checks DB
    # TODO: replace with DB lookup + bcrypt.checkpw(password, hash)
    DEMO_OPERATORS = {
        "operator@oyvoda.com": {
            "id": "op_001",
            "password": "OyvodaDemo2026!",  # plaintext only for demo; prod uses bcrypt
            "name": "Founding Operator",
            "company": "30A Florida Properties",
            "role": "owner",
            "properties": 50,
            "pms": "Escapia"
        }
    }'''

new = '''    # Operator credentials loaded from Railway env vars — never hardcoded
    # Set OPERATOR_1_EMAIL, OPERATOR_1_PASSWORD, OPERATOR_1_ID, etc. in Railway
    DEMO_OPERATORS = {}
    for _i in range(1, 6):
        _email = os.getenv(f"OPERATOR_{_i}_EMAIL", "").strip().lower()
        _pw    = os.getenv(f"OPERATOR_{_i}_PASSWORD", "")
        _oid   = os.getenv(f"OPERATOR_{_i}_ID", f"op_{_i:03d}")
        _name  = os.getenv(f"OPERATOR_{_i}_NAME", "Operator")
        _co    = os.getenv(f"OPERATOR_{_i}_COMPANY", "Properties")
        if _email and _pw:
            DEMO_OPERATORS[_email] = {
                "id": _oid, "password": _pw, "name": _name,
                "company": _co, "role": "owner", "properties": 50, "pms": "Escapia"
            }
    # Fallback demo account only if no env operators configured
    if not DEMO_OPERATORS:
        DEMO_OPERATORS["operator@oyvoda.com"] = {
            "id": "op_001", "password": "OyvodaDemo2026!",
            "name": "Demo Operator", "company": "Demo Properties",
            "role": "owner", "properties": 0, "pms": "Escapia"
        }'''

if old in src:
    src = src.replace(old, new, 1)
    print("OK: credentials block replaced")
else:
    print("WARNING: could not find exact block — searching for fallback pattern")
    import re
    # Try to find and replace the DEMO_OPERATORS dict
    pattern = r'    # Demo credentials.*?    \}'
    match = re.search(pattern, src, re.DOTALL)
    if match:
        src = src[:match.start()] + new + src[match.end():]
        print("OK: replaced via regex")
    else:
        print("ERROR: could not patch — edit manually")
        exit(1)

# Also remove the demo hint from the login page HTML if present
demo_hint = '''              <div class="demo-hint">
                <strong>Demo credentials</strong><br>
                operator@oyvoda.com / OyvodaDemo2026!
              </div>'''

if demo_hint in src:
    src = src.replace(demo_hint, "", 1)
    print("OK: demo hint removed from login page")
else:
    # Try to find any demo-hint div
    import re
    hint_match = re.search(r'\s*<div class="demo-hint">.*?</div>', src, re.DOTALL)
    if hint_match:
        src = src[:hint_match.start()] + src[hint_match.end():]
        print("OK: demo hint removed via regex")
    else:
        print("NOTE: demo hint not found (may already be removed)")

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

# Verify
with open(path, "r") as f:
    check = f.read()

env_based = "OPERATOR_1_EMAIL" in check
no_hardcoded = "OyvodaDemo2026!" not in check or "if not DEMO_OPERATORS" in check
print(f"\nEnv-based auth: {env_based}")
print(f"Hardcoded password protected: {no_hardcoded}")
if env_based:
    print("\nSUCCESS — now set these in Railway:")
    print("  OPERATOR_1_EMAIL    = owner@theiremail.com")
    print("  OPERATOR_1_PASSWORD = TheirPassword123!")
    print("  OPERATOR_1_ID       = UUID-from-pre-booking-setup")
    print("  OPERATOR_1_NAME     = Owner Full Name")
    print("  OPERATOR_1_COMPANY  = Their Company Name")
