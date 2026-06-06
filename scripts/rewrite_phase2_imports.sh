#!/usr/bin/env bash
#
# rewrite_phase2_imports.sh
#
# Rewrites import paths across app/, tests/, scripts/ for the nine
# brain-helper files moved from app/services/concierge/ into
# app/services/messaging_brain/ in Phase 2 Commit 2.
#
# Run this AFTER the git mv operations (so the new files exist at their
# new paths) but BEFORE the commit (so the rewrite and the rename land
# together).
#
# Handles macOS vs Linux sed -i argument quirk by detecting the OS.
#
# Usage:
#   bash scripts/rewrite_phase2_imports.sh
#
# Run from repo root.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Detect sed flavor. macOS BSD sed needs `-i ''`, GNU sed (Linux) needs `-i`.
if sed --version >/dev/null 2>&1; then
  SED_INPLACE=(sed -i)
else
  SED_INPLACE=(sed -i '')
fi

# The nine import path rewrites. Each line is `OLD|NEW`.
# Order matters only for sed efficiency, not correctness — each pattern is
# unique enough that no later pattern matches an already-rewritten path.
declare -a REWRITES=(
  "app\.services\.concierge\.scoped_knowledge_service|app.services.messaging_brain.knowledge.scoped_knowledge_service"
  "app\.services\.concierge\.context_builder|app.services.messaging_brain.context.property_facts"
  "app\.services\.concierge\.operator_guidance|app.services.messaging_brain.context.operator_guidance"
  "app\.services\.concierge\.knowledge_topic_registry|app.services.messaging_brain.knowledge.topic_registry"
  "app\.services\.concierge\.topic_classifier|app.services.messaging_brain.intake.topic_classifier"
  "app\.services\.concierge\.intent_classification_escalator|app.services.messaging_brain.intake.intent_escalator"
  "app\.services\.concierge\.conversation_history_service|app.services.messaging_brain.context.conversation_history"
  "app\.services\.concierge\.response_reviewer|app.services.messaging_brain.grounding.response_reviewer"
  "app\.services\.concierge\.hallucination_guard|app.services.messaging_brain.grounding.hallucination_guard"
)

# Build the sed -e arguments.
sed_args=()
for rewrite in "${REWRITES[@]}"; do
  old="${rewrite%|*}"
  new="${rewrite#*|}"
  sed_args+=("-e" "s|${old}|${new}|g")
done

# Search paths.
search_paths=("app")
[[ -d tests ]] && search_paths+=("tests")
[[ -d scripts ]] && search_paths+=("scripts")

echo "Rewriting imports across: ${search_paths[*]}"
echo ""

# Run the rewrite.
find "${search_paths[@]}" -name '*.py' -type f -exec "${SED_INPLACE[@]}" "${sed_args[@]}" {} +

echo "Done. Verify with:"
echo "  bash scripts/verify_phase2_transplant.sh post-commit-2"
