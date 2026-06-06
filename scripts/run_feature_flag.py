#!/usr/bin/env python3
"""Run a feature-flag flip via FeatureFlagService.set_flag.

Whitelisted to the messaging-brain rich-context flag pair. Other flags
have dedicated rollout paths (staged_rollout.py for the runtime/shadow
canary pair) and are intentionally not exposed here.

Usage (dry-run):
    python -m scripts.run_feature_flag \\
        --flag MESSAGING_BRAIN_RICH_CONTEXT_SHADOW \\
        --company-id <uuid> \\
        --direction enable \\
        --enabled-by "<your name or handle>" \\
        --dry-run

Usage (real write):
    python -m scripts.run_feature_flag \\
        --flag MESSAGING_BRAIN_RICH_CONTEXT_SHADOW \\
        --company-id <uuid> \\
        --direction enable \\
        --enabled-by "<your name or handle>" \\
        --notes "Session 13 Phase A shadow rollout for <tenant>" \\
        --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.services.feature_flags import FeatureFlag, get_feature_flags

# Whitelist. Other flags have dedicated rollout paths; widen this list
# only with deliberate review.
#
# CLI takes the enum-style name (readable in shell history); the script
# maps to the stored flag value before any DB write.
FLAG_MAP = {
    "MESSAGING_BRAIN_RICH_CONTEXT_SHADOW": (
        FeatureFlag.MESSAGING_BRAIN_RICH_CONTEXT_SHADOW
    ),
    "MESSAGING_BRAIN_RICH_CONTEXT": FeatureFlag.MESSAGING_BRAIN_RICH_CONTEXT,
}

DIRECTIONS = ("enable", "disable")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flip a messaging-brain rich-context feature flag.",
    )
    parser.add_argument(
        "--flag",
        required=True,
        choices=tuple(FLAG_MAP.keys()),
        help="Flag name. Whitelisted to the rich-context pair.",
    )
    parser.add_argument(
        "--company-id",
        required=True,
        help="Operator UUID (company_id).",
    )
    parser.add_argument(
        "--property-code",
        default=None,
        help="Optional property scope. Omit for company-level scope.",
    )
    parser.add_argument(
        "--direction",
        required=True,
        choices=DIRECTIONS,
        help="enable or disable.",
    )
    parser.add_argument(
        "--enabled-by",
        required=True,
        help="Who is making this change. Recorded in the audit column.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Notes for the audit column. Required for real writes; optional for --dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for real writes. Without --yes and without --dry-run, the script refuses to run.",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    """Validate args. Print and exit on failure."""
    try:
        uuid.UUID(args.company_id)
    except ValueError:
        print(
            f"ERROR: --company-id must be a valid UUID, got: "
            f"{args.company_id}"
        )
        sys.exit(1)

    if not args.dry_run and not args.yes:
        print(
            "ERROR: real writes require --yes. Re-run with --dry-run "
            "to inspect, or add --yes to commit."
        )
        sys.exit(1)

    if not args.dry_run and not args.notes:
        print("ERROR: --notes is required for real writes.")
        sys.exit(1)


def _print_summary(
    args: argparse.Namespace,
    *,
    header: str,
    stored_flag: str,
) -> None:
    """Print a structured summary of the operation."""
    enabled = args.direction == "enable"
    print(header)
    print(f"  flag (CLI):    {args.flag}")
    print(f"  flag (stored): {stored_flag}")
    print(f"  company_id:    {args.company_id}")
    print(f"  property_code: {args.property_code or '(none - company scope)'}")
    print(f"  direction:     {args.direction}  (enabled={enabled})")
    print(f"  enabled_by:    {args.enabled_by}")
    print(f"  notes:         {args.notes or '(none)'}")
    print()


async def _read_back(
    db,
    args: argparse.Namespace,
    *,
    stored_flag: str,
) -> bool:
    """Read the persisted row and print it. Returns True if found."""
    from sqlalchemy import text

    result = await db.execute(
        text(
            """
            SELECT enabled, enabled_at, enabled_by, notes
            FROM operator_feature_flags
            WHERE flag_name = :flag
              AND (
                    (company_id = :cid AND :cid IS NOT NULL)
                    OR (company_id IS NULL AND :cid IS NULL)
              )
              AND (
                    (property_code = :prop AND :prop IS NOT NULL)
                    OR (property_code IS NULL AND :prop IS NULL)
              )
            LIMIT 1
            """
        ),
        {
            "flag": stored_flag,
            "cid": args.company_id,
            "prop": args.property_code,
        },
    )
    row = result.fetchone()
    if row is None:
        print(
            "ERROR: read-back found no matching row. set_flag returned "
            "True but the row is not visible. Investigate before "
            "treating the flip as complete."
        )
        return False
    print("Persisted row:")
    print(f"  enabled:    {row.enabled}")
    print(f"  enabled_at: {row.enabled_at}")
    print(f"  enabled_by: {row.enabled_by}")
    print(f"  notes:      {row.notes}")
    print()
    return True


async def _run(args: argparse.Namespace) -> int:
    from app.db.session import SessionLocal

    enabled = args.direction == "enable"
    stored_flag = FLAG_MAP[args.flag]

    if args.dry_run:
        _print_summary(
            args,
            header="(dry-run - no rows will be written)",
            stored_flag=stored_flag,
        )
        print("No further action. Re-run without --dry-run and with --yes to commit.")
        return 0

    _print_summary(args, header="Writing flag:", stored_flag=stored_flag)

    async with SessionLocal() as db:
        ok = await get_feature_flags(db).set_flag(
            stored_flag,
            enabled,
            company_id=args.company_id,
            property_code=args.property_code,
            enabled_by=args.enabled_by,
            notes=args.notes,
        )
        if not ok:
            print("ERROR: set_flag returned False. Write did not succeed.")
            return 1

        print("set_flag returned True. Reading row back for confirmation.")
        print()
        found = await _read_back(db, args, stored_flag=stored_flag)
        if not found:
            return 1

    print(
        "Done. Note: in-process flag cache TTL is 300s; new behavior "
        "may not be visible on all workers until that window elapses."
    )
    return 0


def main() -> int:
    args = _parse_args()
    _validate_args(args)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
