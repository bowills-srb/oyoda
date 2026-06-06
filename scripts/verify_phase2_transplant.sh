#!/usr/bin/env bash
#
# verify_phase2_transplant.sh
#
# Phase 2 transplant verification helper. Run this script:
#   - BEFORE Commit 1 to verify legacy /concierge/message is safe to delete
#   - AFTER each Phase 2 commit to verify nothing was missed
#
# Exit code: 0 if all checks pass, 1 if any check fails. Each check
# prints its own pass/fail line so you can see exactly what tripped.
#
# Usage:
#   bash scripts/verify_phase2_transplant.sh pre-commit-1
#   bash scripts/verify_phase2_transplant.sh post-commit-1
#   bash scripts/verify_phase2_transplant.sh post-commit-2
#   bash scripts/verify_phase2_transplant.sh post-commit-3
#   bash scripts/verify_phase2_transplant.sh all
#
# Run from the repo root. Assumes app/, tests/, scripts/ are present.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

phase="${1:-all}"
failures=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; failures=$((failures + 1)); }
header() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# Helper: assert no matches for a grep pattern in app/ tests/ scripts/.
# Prints the matches if any are found.
expect_no_matches() {
  local pattern="$1"
  local description="$2"
  local search_paths=("app/")
  if [[ -d tests ]]; then search_paths+=("tests/"); fi
  if [[ -d scripts ]]; then search_paths+=("scripts/"); fi

  local matches
  matches=$(grep -rn --include='*.py' "$pattern" "${search_paths[@]}" 2>/dev/null || true)
  if [[ -z "$matches" ]]; then
    pass "$description"
  else
    fail "$description"
    printf '%s\n' "$matches" | sed 's/^/        /'
  fi
}

# Helper: assert a file exists.
expect_file_exists() {
  local path="$1"
  if [[ -f "$path" ]]; then
    pass "exists: $path"
  else
    fail "missing: $path"
  fi
}

# Helper: assert a file does NOT exist.
expect_file_absent() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    pass "deleted: $path"
  else
    fail "still present: $path"
  fi
}

# ============================================================================
# Pre-Commit-1 verification
# Goal: confirm the legacy /concierge/message pipeline is safe to delete.
# Logs check is manual (Railway dashboard); this script verifies the code
# side — that the legacy runtime is internally consistent with deletion.
# ============================================================================
run_pre_commit_1() {
  header "Pre-Commit-1: legacy concierge runtime audit"
  echo "  Confirm via Railway logs (last 14 days) that /api/v1/concierge/message"
  echo "  has either zero hits OR all hits send auto_track_maintenance=True."
  echo "  This script does NOT check logs — verify manually before proceeding."
  echo ""

  # The three legacy runtime files should still exist before Commit 1.
  expect_file_exists "app/services/concierge/ai_concierge.py"
  expect_file_exists "app/services/concierge/concierge_intelligence.py"
  expect_file_exists "app/services/concierge/concierge_runner.py"

  # The brain runtime path should be wired (sanity check that the brain
  # side is alive and we're not about to delete the only working path).
  expect_file_exists "app/services/messaging_brain/orchestrator.py"
  expect_file_exists "app/services/messaging_brain/agents/intake_agent.py"
}

# ============================================================================
# Post-Commit-1 verification
# Goal: confirm the three legacy runtime files are gone, no stragglers
# import them, and _handle_via_existing is gone from the endpoint.
# ============================================================================
run_post_commit_1() {
  header "Post-Commit-1: legacy runtime deletion"

  # Files should be gone.
  expect_file_absent "app/services/concierge/ai_concierge.py"
  expect_file_absent "app/services/concierge/concierge_intelligence.py"
  expect_file_absent "app/services/concierge/concierge_runner.py"

  # No imports of the deleted files should remain anywhere.
  expect_no_matches "app\.services\.concierge\.ai_concierge" \
    "no imports of app.services.concierge.ai_concierge"
  expect_no_matches "app\.services\.concierge\.concierge_intelligence" \
    "no imports of app.services.concierge.concierge_intelligence"
  expect_no_matches "app\.services\.concierge\.concierge_runner" \
    "no imports of app.services.concierge.concierge_runner"

  # No imports of the removed __init__.py exports.
  expect_no_matches "from app\.services\.concierge import.*ConciergeRunner" \
    "no imports of ConciergeRunner from concierge package"
  expect_no_matches "from app\.services\.concierge import.*classify_intent" \
    "no imports of classify_intent from concierge package"
  expect_no_matches "from app\.services\.concierge import.*get_concierge_runner" \
    "no imports of get_concierge_runner from concierge package"

  # _handle_via_existing should be gone from the endpoint.
  expect_no_matches "_handle_via_existing" \
    "no references to _handle_via_existing"

  # The auto_track_maintenance escape hatch should be gone.
  # We look for the specific gating pattern, not the parameter name itself
  # (which may legitimately appear elsewhere as a request field).
  expect_no_matches "auto_track_maintenance.*False" \
    "no auto_track_maintenance=False conditional gates"
  expect_no_matches "not request\.auto_track_maintenance" \
    "no 'not request.auto_track_maintenance' conditional gates"
  expect_no_matches "if request\.auto_track_maintenance is False" \
    "no 'if request.auto_track_maintenance is False' gates"
}

# ============================================================================
# Post-Commit-2 verification
# Goal: confirm all nine transplant files are at their new paths,
# the old paths are gone, and no stragglers import the old paths.
# ============================================================================
run_post_commit_2() {
  header "Post-Commit-2: brain helper transplant"

  # New paths exist.
  expect_file_exists "app/services/messaging_brain/knowledge/scoped_knowledge_service.py"
  expect_file_exists "app/services/messaging_brain/context/property_facts.py"
  expect_file_exists "app/services/messaging_brain/context/operator_guidance.py"
  expect_file_exists "app/services/messaging_brain/knowledge/topic_registry.py"
  expect_file_exists "app/services/messaging_brain/intake/topic_classifier.py"
  expect_file_exists "app/services/messaging_brain/intake/intent_escalator.py"
  expect_file_exists "app/services/messaging_brain/context/conversation_history.py"
  expect_file_exists "app/services/messaging_brain/grounding/response_reviewer.py"
  expect_file_exists "app/services/messaging_brain/grounding/hallucination_guard.py"

  # New subdirectories have __init__.py.
  expect_file_exists "app/services/messaging_brain/context/__init__.py"
  expect_file_exists "app/services/messaging_brain/intake/__init__.py"
  expect_file_exists "app/services/messaging_brain/grounding/__init__.py"

  # Old paths are gone.
  expect_file_absent "app/services/concierge/scoped_knowledge_service.py"
  expect_file_absent "app/services/concierge/context_builder.py"
  expect_file_absent "app/services/concierge/operator_guidance.py"
  expect_file_absent "app/services/concierge/knowledge_topic_registry.py"
  expect_file_absent "app/services/concierge/topic_classifier.py"
  expect_file_absent "app/services/concierge/intent_classification_escalator.py"
  expect_file_absent "app/services/concierge/conversation_history_service.py"
  expect_file_absent "app/services/concierge/response_reviewer.py"
  expect_file_absent "app/services/concierge/hallucination_guard.py"

  # No imports point at the old paths.
  expect_no_matches "app\.services\.concierge\.scoped_knowledge_service" \
    "no imports of old scoped_knowledge_service path"
  expect_no_matches "app\.services\.concierge\.context_builder\b" \
    "no imports of old context_builder path"
  expect_no_matches "app\.services\.concierge\.operator_guidance" \
    "no imports of old operator_guidance path"
  expect_no_matches "app\.services\.concierge\.knowledge_topic_registry" \
    "no imports of old knowledge_topic_registry path"
  expect_no_matches "app\.services\.concierge\.topic_classifier" \
    "no imports of old topic_classifier path"
  expect_no_matches "app\.services\.concierge\.intent_classification_escalator" \
    "no imports of old intent_classification_escalator path"
  expect_no_matches "app\.services\.concierge\.conversation_history_service" \
    "no imports of old conversation_history_service path"
  expect_no_matches "app\.services\.concierge\.response_reviewer" \
    "no imports of old response_reviewer path"
  expect_no_matches "app\.services\.concierge\.hallucination_guard" \
    "no imports of old hallucination_guard path"

  # The concierge package __init__.py should no longer export the
  # transplanted symbols. We grep the file content directly so the check
  # is independent of how the exports are spelled.
  if [[ -f "app/services/concierge/__init__.py" ]]; then
    local init_content
    init_content=$(cat app/services/concierge/__init__.py)
    for symbol in \
      "scoped_knowledge_service" \
      "context_builder" \
      "operator_guidance" \
      "knowledge_topic_registry" \
      "topic_classifier" \
      "intent_classification_escalator" \
      "conversation_history_service" \
      "response_reviewer" \
      "hallucination_guard"; do
      if echo "$init_content" | grep -q "\"$symbol\""; then
        fail "concierge/__init__.py still references $symbol in _EXPORTS"
      else
        pass "concierge/__init__.py no longer references $symbol"
      fi
    done
  fi
}

# ============================================================================
# Post-Commit-3 verification
# Goal: confirm the preservation banner is present on all 12 future-feature
# files. We grep for a distinctive marker string that won't appear in any
# other file.
# ============================================================================
run_post_commit_3() {
  header "Post-Commit-3: future-feature preservation banners"

  local marker="PRESERVATION STATUS (post-Phase-1"
  local files=(
    "app/services/concierge/dining_service.py"
    "app/services/concierge/event_planning_service.py"
    "app/services/concierge/bd_insight_service.py"
    "app/services/concierge/portfolio_availability_service.py"
    "app/services/concierge/market_brain.py"
    "app/services/concierge/market_source_adapters.py"
    "app/services/concierge/group_session.py"
    "app/services/concierge/guest_profile_service.py"
    "app/services/concierge/operator_learning.py"
    "app/services/concierge/escapia_unified.py"
    "app/services/concierge/maintenance_service.py"
  )
  for f in "${files[@]}"; do
    if [[ ! -f "$f" ]]; then
      fail "file missing entirely: $f"
      continue
    fi
    if grep -F -q "$marker" "$f"; then
      pass "banner present: $f"
    else
      fail "banner missing: $f"
    fi
  done
}

# ============================================================================
# Dispatch
# ============================================================================
case "$phase" in
  pre-commit-1)   run_pre_commit_1 ;;
  post-commit-1)  run_post_commit_1 ;;
  post-commit-2)  run_post_commit_2 ;;
  post-commit-3)  run_post_commit_3 ;;
  all)
    run_post_commit_1
    run_post_commit_2
    run_post_commit_3
    ;;
  *)
    echo "Unknown phase: $phase"
    echo "Usage: $0 {pre-commit-1|post-commit-1|post-commit-2|post-commit-3|all}"
    exit 2
    ;;
esac

echo ""
if [[ $failures -eq 0 ]]; then
  printf '\033[32m== ALL CHECKS PASSED ==\033[0m\n'
  exit 0
else
  printf '\033[31m== %d CHECK(S) FAILED ==\033[0m\n' "$failures"
  exit 1
fi
