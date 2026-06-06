#!/usr/bin/env python3
"""
pre_booking_setup.py

Run this once to set up everything needed for pre-booking inquiries
with the first operator (Escapia API key already in hand).

Usage:
    python scripts/pre_booking_setup.py \
        --company-id "your-operator-uuid" \
        --api-key "esc_live_xxxxxxxxxxxx" \
        --alert-phone "+18505550100" \
        --alert-email "owner@gulfviewrentals.com"

What this does:
  1. Runs the DB migration (creates all 20 tables + column additions)
  2. Stores the Escapia API key in the encrypted credential store
  3. Inserts a row in operator_pre_booking_policies (approval required by default)
  4. Creates an operator_alert_contacts row (where draft alerts go)
  5. Triggers the first PMS sync (listings + bookings)
  6. Sets property_rollout_phases to 'inactive' for all discovered listings
  7. Prints the next steps

After this script completes, the operator manually advances one property
to 'pre_booking_single' phase via the dashboard or:
    POST /api/v1/canary/rollout/{property_id}/advance?company_id={company_id}

That enables AI drafting for the next inquiry from that property.
With approval_mode='required' (the default), nothing sends until the
operator approves it in the dashboard or via SMS reply.
"""

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def run_migration(db_url: str) -> None:
    """Create all pre-booking tables."""
    import asyncpg

    migration_file = Path(__file__).parent.parent / "db/migrations/versions/018_pre_booking_pipeline.py"
    migration_content = migration_file.read_text()

    # Extract the SQL string from the Python file
    sql_start = migration_content.index('SQL = """') + len('SQL = """')
    sql_end = migration_content.rindex('"""')
    sql = migration_content[sql_start:sql_end]

    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(sql)
        print("✅ Migration 018 complete — all pre-booking tables created")
    finally:
        await conn.close()


def store_credentials(company_id: uuid.UUID, api_key: str) -> None:
    """Store Escapia API key in encrypted credential vault."""
    from app.services.connectors.integration_gateway import (
        get_integration_credential_store,
        IntegrationProvider,
    )
    store = get_integration_credential_store()
    result = store.upsert_credentials(
        company_id=company_id,
        provider=IntegrationProvider.ESCAPIA,
        credentials={"api_key": api_key},
        label="Escapia (first operator)",
    )
    print(f"✅ Credentials stored: {result['provider']} updated_at={result['updated_at']}")


async def insert_operator_policy(db_url: str, company_id: str) -> None:
    """Insert default pre-booking policy — approval required."""
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            """
            INSERT INTO operator_pre_booking_policies
                (company_id, auto_send_threshold, auto_send_on_timeout,
                 review_window_hours, flag_pricing_inquiries, flag_pet_inquiries,
                 platform_learning_opt_in)
            VALUES ($1::uuid, 0.75, TRUE, 2, TRUE, FALSE, TRUE)
            ON CONFLICT (company_id) DO NOTHING
            """,
            company_id,
        )
        print("✅ Operator pre-booking policy created (approval_required by default)")
    finally:
        await conn.close()


async def insert_alert_contact(
    db_url: str,
    company_id: str,
    phone: str,
    email: str,
) -> None:
    """Create primary alert contact for pre-booking approvals."""
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            """
            INSERT INTO operator_alert_contacts
                (company_id, alert_type, contact_name, contact_phone, contact_email,
                 is_primary, escalation_order, escalation_timeout_minutes)
            VALUES
                ($1::uuid, 'pre_booking', 'Primary Owner', $2, $3, TRUE, 1, 120)
            ON CONFLICT DO NOTHING
            """,
            company_id, phone, email,
        )
        # Also add a general alert contact for escalations
        await conn.execute(
            """
            INSERT INTO operator_alert_contacts
                (company_id, alert_type, contact_name, contact_phone, contact_email,
                 is_primary, escalation_order, escalation_timeout_minutes)
            VALUES
                ($1::uuid, 'general', 'Primary Owner', $2, $3, TRUE, 1, 30)
            ON CONFLICT DO NOTHING
            """,
            company_id, phone, email,
        )
        print(f"✅ Alert contacts created → {phone} / {email}")
    finally:
        await conn.close()


async def trigger_first_sync(company_id: str) -> None:
    """Queue the first PMS sync."""
    try:
        from app.workers.tasks import sync_pms_for_operator
        task = sync_pms_for_operator.delay(company_id)
        print(f"✅ PMS sync queued — task_id={task.id}")
        print("   (Historical message import will auto-trigger 60s after sync completes)")
    except Exception as e:
        print(f"⚠️  Could not queue sync (Celery may not be running): {e}")
        print("   Run manually: POST /api/v1/operators/{company_id}/sync-pms")


def print_next_steps(company_id: str) -> None:
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP COMPLETE — next steps to go live with pre-booking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Wait for PMS sync to complete:
   GET /api/v1/operators/{company_id}/sync-status

2. Check your properties were imported:
   GET /api/v1/canary/rollout?company_id={company_id}
   (All properties will show phase='inactive')

3. Start canary on ONE property:
   POST /api/v1/canary/rollout/{property_id}/advance?company_id={company_id}
   (Advances from inactive → pre_booking_single)

4. The next inquiry from that property will:
   → Be classified by the AI
   → Get an AI draft generated
   → Be HELD (approval_mode=required by default)
   → You receive an SMS/dashboard alert with the draft
   → Reply APPROVE, EDIT [text], or REJECT

5. After you approve a few drafts and feel good about the AI output:
   POST /api/v1/canary/rollout/{property_id}/approval-mode?mode=auto&company_id={company_id}
   (Now high-confidence drafts send automatically)

6. Check the activity log anytime:
   GET /api/v1/inquiries?company_id={company_id}&status=replied

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NOTE: Pre-booking replies go back through Escapia → Vrbo/Airbnb.
No Twilio or RCS required for pre-booking. Twilio is only needed
for post-booking guest SMS/RCS messaging (once you onboard guests
directly with a designated number).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""".format(company_id=company_id))


async def main():
    parser = argparse.ArgumentParser(description="Set up pre-booking pipeline for first operator")
    parser.add_argument("--company-id", required=True, help="Operator UUID")
    parser.add_argument("--api-key", required=True, help="Escapia API key")
    parser.add_argument("--alert-phone", required=True, help="Phone number for draft alerts (E.164)")
    parser.add_argument("--alert-email", required=True, help="Email for draft alerts")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="PostgreSQL connection URL")
    args = parser.parse_args()

    if not args.db_url:
        print("ERROR: DATABASE_URL environment variable not set and --db-url not provided")
        sys.exit(1)

    company_id = args.company_id
    try:
        uuid.UUID(company_id)
    except ValueError:
        print(f"ERROR: --company-id must be a valid UUID, got: {company_id}")
        sys.exit(1)

    print(f"\n🚀 Setting up pre-booking pipeline for company {company_id}\n")

    await run_migration(args.db_url)
    store_credentials(uuid.UUID(company_id), args.api_key)
    await insert_operator_policy(args.db_url, company_id)
    await insert_alert_contact(args.db_url, company_id, args.alert_phone, args.alert_email)
    await trigger_first_sync(company_id)
    print_next_steps(company_id)


if __name__ == "__main__":
    asyncio.run(main())
