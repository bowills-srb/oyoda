#!/usr/bin/env python3
"""
fix_model_names.py — Fixes Groq model IDs throughout the codebase.

Llama 4 Scout requires the full namespaced ID: meta-llama/llama-4-scout-17b-16e-instruct
Without the prefix, Groq returns model_not_found.

Also sets llama-3.3-70b-versatile as the fallback (widely available, confirmed working).

Run from ~/Downloads/oyvoda/:
    python3 fix_model_names.py
"""

import os

FILES = [
    "app/services/concierge/ai_concierge.py",
    "app/services/concierge/concierge_intelligence.py",
    "app/api/v1/endpoints/landing.py",
    "app/core/config.py",
]

REPLACEMENTS = [
    # Wrong bare name -> correct namespaced name
    ('"llama-4-scout-17b-16e-instruct"',   '"meta-llama/llama-4-scout-17b-16e-instruct"'),
    ("'llama-4-scout-17b-16e-instruct'",   "'meta-llama/llama-4-scout-17b-16e-instruct'"),
    # Old fallback model (deprecated) -> current stable fallback
    ('"llama-3.1-70b-versatile"',           '"llama-3.3-70b-versatile"'),
    ("'llama-3.1-70b-versatile'",           "'llama-3.3-70b-versatile'"),
    # Config default model
    ('groq_model: str = "llama-4-scout-17b-16e-instruct"',
     'groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"'),
    ('ai_model_default: str = "llama-4-scout-17b-16e-instruct"',
     'ai_model_default: str = "meta-llama/llama-4-scout-17b-16e-instruct"'),
]

results = {}

for filepath in FILES:
    if not os.path.exists(filepath):
        results[filepath] = "SKIPPED (not found)"
        continue

    with open(filepath, "r", encoding="utf-8") as f:
        src = f.read()

    original = src
    changes = []
    for old, new in REPLACEMENTS:
        if old in src:
            count = src.count(old)
            src = src.replace(old, new)
            changes.append(f"  {old!r} -> {new!r} ({count}x)")

    if src != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(src)
        results[filepath] = f"UPDATED ({len(changes)} change(s))\n" + "\n".join(changes)
    else:
        results[filepath] = "NO CHANGES (already correct or pattern not found)"

print()
for path, result in results.items():
    print(f"{path}:")
    print(f"  {result}")
    print()

# Quick verification
print("=== Verification ===")
for filepath in FILES:
    if not os.path.exists(filepath):
        continue
    with open(filepath, "r") as f:
        content = f.read()
    has_scout = "meta-llama/llama-4-scout" in content
    has_old_bare = '"llama-4-scout-17b-16e-instruct"' in content and "meta-llama/" not in content
    has_3_3 = "llama-3.3-70b-versatile" in content
    print(f"  {os.path.basename(filepath)}: scout_correct={has_scout} bare_wrong={has_old_bare} fallback_3_3={has_3_3}")
