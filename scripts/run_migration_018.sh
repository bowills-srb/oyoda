#!/bin/bash
# =============================================================================
# run_migration_018.sh
#
# Runs the full pre-booking pipeline migration against your local database.
# Run this from the project root:
#
#   chmod +x scripts/run_migration_018.sh
#   ./scripts/run_migration_018.sh
#
# What it does:
#   1. Connects to the database defined in .env
#   2. Creates all 20 tables the pre-booking pipeline needs
#   3. Adds columns to existing tables (safe to re-run — uses IF NOT EXISTS)
#   4. Prints a summary of what was created
# =============================================================================

set -e  # Exit on first error

# ── Load DATABASE_URL from .env ───────────────────────────────────────────────
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep DATABASE_URL | xargs)
fi

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL not found in .env"
    echo "Expected format: DATABASE_URL=postgresql+asyncpg://user:pass@host:port/dbname"
    exit 1
fi

# Strip the +asyncpg driver suffix for psql
PG_URL=$(echo "$DATABASE_URL" | sed 's|postgresql+asyncpg|postgresql|')

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Migration 018 — Pre-Booking Pipeline"
echo " Target: $PG_URL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

psql "$PG_URL" -f scripts/migration_018.sql

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Migration complete. Verifying tables..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

psql "$PG_URL" -c "
SELECT table_name, 
       (SELECT COUNT(*) FROM information_schema.columns 
        WHERE table_name = t.table_name AND table_schema = 'public') AS column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_name IN (
    'companies', 'operator_feature_flags', 'pms_listings', 'pms_bookings',
    'operator_sync_log', 'listing_id_aliases', 'escapia_message_history',
    'message_orphan_queue', 'pre_booking_inquiries', 'operator_pre_booking_policies',
    'property_rollout_phases', 'property_rollout_history', 'operator_learned_preferences',
    'operator_draft_events', 'platform_learning_events', 'platform_intelligence',
    'gate_code_deliveries', 'operator_alert_contacts', 'operator_alert_acks',
    'operator_alert_log'
  )
ORDER BY table_name;
"

echo ""
echo "✅ All done. Next step:"
echo "   python scripts/pre_booking_setup.py \\"
echo "     --company-id '<your-operator-uuid>' \\"
echo "     --api-key 'esc_live_...' \\"
echo "     --alert-phone '+1850...' \\"
echo "     --alert-email 'owner@example.com'"
echo ""
