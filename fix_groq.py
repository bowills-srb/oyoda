#!/usr/bin/env python3
"""
fix_groq.py — Patches ai_concierge.py to use GROQ_API_KEY instead of GOOGLE_API_KEY.
Run from ~/Downloads/oyvoda/:
    python3 fix_groq.py
"""
import re

path = "app/services/concierge/ai_concierge.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

original_len = len(src)
changes = []

# ── Patch 1: Replace api_key lookup with groq_key + gemini_key ──────────────
old1 = 'api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")\n    if not api_key:'
new1 = 'groq_key = os.getenv("GROQ_API_KEY", "")\n    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")\n    if not groq_key and not gemini_key:'
if old1 in src:
    src = src.replace(old1, new1, 1)
    changes.append("Patch 1: api_key -> groq_key + gemini_key")
else:
    changes.append("Patch 1: SKIPPED (already applied or text differs)")

# ── Patch 2: Fix the fallback keyword check (api_key -> uses groq_key now) ──
# The _keyword_fallback call at end of function doesn't need changing,
# but the Gemini URL still references {api_key} which no longer exists.
old2 = 'generateContent?key={api_key}"'
new2 = 'generateContent?key={gemini_key}"'
if old2 in src:
    src = src.replace(old2, new2, 1)
    changes.append("Patch 2: Gemini URL now uses gemini_key")
else:
    changes.append("Patch 2: SKIPPED (already applied)")

# ── Patch 3: Update system prompt to be warmer + add Groq call ───────────────
# Find the Gemini call block and prepend a Groq call before it
groq_block = '''    # -- Groq call (primary -- OpenAI-compatible) --------------------------------
    if groq_key:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-4-scout-17b-16e-instruct",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "max_tokens": 300,
                        "temperature": 0.72,
                    },
                    timeout=8.0,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as _ge:
            logger.warning(f"Groq legacy path failed: {_ge}")

'''

# Find where the Gemini call block begins
gemini_marker = '    # -- Gemini call'
gemini_marker2 = '    # \u2500\u2500 Gemini call'  # with unicode dash

if gemini_marker not in src and gemini_marker2 in src:
    gemini_marker = gemini_marker2

if groq_block.strip()[:30] not in src:
    if gemini_marker in src:
        src = src.replace(gemini_marker, groq_block + gemini_marker, 1)
        changes.append("Patch 3: Groq call block inserted before Gemini")
    else:
        # Try to insert before the payload = { line
        old3 = '    payload = {\n        "contents":'
        if old3 in src:
            src = src.replace(old3, groq_block + old3, 1)
            changes.append("Patch 3: Groq call block inserted (via payload marker)")
        else:
            changes.append("Patch 3: SKIPPED - couldn't find insertion point")
else:
    changes.append("Patch 3: SKIPPED (already applied)")

# ── Patch 4: Improve the system prompt to be warmer ─────────────────────────
old4 = (
    'f"You are {concierge_name} {concierge_emoji}, the personal beach concierge for {guest_name} staying at {property_name}.\\n"\n'
    '        f"Style: warm, brief (2 sentences max unless detail is needed), helpful local friend. {eq_hint}\\n"\n'
    '        f"Context: {phase_hint}\\n"\n'
    '        + (f"Guest history: {repeat_snippet}\\n" if repeat_snippet else "")\n'
    '        + f"Escalations: direct to {support_phone}."'
)
new4 = (
    'f"You are {concierge_name}, personal concierge for {guest_name} at {property_name}.\\n"\n'
    '        f"Voice: warm, specific, conversational -- like a knowledgeable local friend texting, never robotic.\\n"\n'
    '        f"Always use real names for places. Never say I don\'t have that information -- use your local knowledge.\\n"\n'
    '        f"Give 2-3 specific named options when asked for recs. End with an open question.\\n"\n'
    '        f"When a guest picks something, proactively offer the next logical step without waiting.\\n"\n'
    '        f"{phase_hint} {eq_hint}\\n"\n'
    '        + (f"Guest history: {repeat_snippet}\\n" if repeat_snippet else "")\n'
    '        + f"Emergencies: {support_phone}."'
)
if old4 in src:
    src = src.replace(old4, new4, 1)
    changes.append("Patch 4: System prompt updated to warmer voice")
else:
    changes.append("Patch 4: SKIPPED (text differs - may already be updated)")

# ── Write result ─────────────────────────────────────────────────────────────
with open(path, "w", encoding="utf-8") as f:
    f.write(src)

# ── Verify ───────────────────────────────────────────────────────────────────
with open(path, "r") as f:
    check = f.read()

groq_key_present = "GROQ_API_KEY" in check
groq_call_present = "groq.com/openai/v1" in check
gemini_fallback = "gemini_key" in check

print(f"\nFile: {path}")
print(f"Size: {original_len} -> {len(check)} bytes ({len(check)-original_len:+d})")
print()
for c in changes:
    print(f"  {'OK' if 'SKIP' not in c else '--'}  {c}")
print()
print(f"  GROQ_API_KEY referenced: {groq_key_present}")
print(f"  Groq API call wired:     {groq_call_present}")
print(f"  Gemini kept as fallback: {gemini_fallback}")
print()
if groq_key_present and groq_call_present and gemini_fallback:
    print("SUCCESS -- all checks passed")
else:
    print("WARNING -- some checks failed, review the file manually")
    print("  Run: grep -n 'GROQ_API_KEY\\|groq_key\\|groq.com' app/services/concierge/ai_concierge.py")
