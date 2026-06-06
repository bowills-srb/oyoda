"""
One-shot script to reset Lanier's password using the same hashing
function the app uses (SHA-256 prehash → bcrypt). Run:

    python scripts/reset_lanier_password.py

Reads ALEMBIC_DATABASE_URL from env. Hardcoded email + password below —
update and remove after use.
"""
import os
import sys
import hashlib
import bcrypt
from sqlalchemy import create_engine, text


LANIER_EMAIL = "lanier@beachhabitats30a.com"
NEW_PASSWORD = "Betsyhare17!"


def hash_password(plain: str) -> str:
    prehashed = hashlib.sha256(plain.encode("utf-8")).hexdigest().encode("utf-8")
    return bcrypt.hashpw(prehashed, bcrypt.gensalt()).decode("utf-8")


def main() -> int:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: ALEMBIC_DATABASE_URL or DATABASE_URL must be set", file=sys.stderr)
        return 1
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    if LANIER_EMAIL == "REPLACE_WITH_LANIERS_EMAIL":
        print("ERROR: Edit LANIER_EMAIL in this script before running", file=sys.stderr)
        return 1

    new_hash = hash_password(NEW_PASSWORD)
    eng = create_engine(url)
    with eng.begin() as c:
        rows = c.execute(
            text(
                "UPDATE operator_accounts SET password_hash = :h, updated_at = NOW() "
                "WHERE email = :e RETURNING id, email"
            ),
            {"h": new_hash, "e": LANIER_EMAIL},
        ).fetchall()
    if not rows:
        print(f"ERROR: No operator_accounts row found for email={LANIER_EMAIL!r}", file=sys.stderr)
        return 1
    for r in rows:
        print(f"Updated: id={r.id} email={r.email}")
    print(f"Login with password: {NEW_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
