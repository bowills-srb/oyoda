#!/usr/bin/env python3
"""
fix_fallback.py — Replaces the Gemini fallback block in ai_concierge.py
with Claude Haiku. Run from ~/Downloads/oyvoda/:
    python3 fix_fallback.py
"""

path = "app/services/concierge/ai_concierge.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

# The old Gemini block — find and replace entirely
# We'll identify it by the comment + payload pattern
gemini_start = src.find("    # -- Gemini call")
if gemini_start == -1:
    # Try unicode dash version
    gemini_start = src.find("    # \u2500\u2500 Gemini call")
if gemini_start == -1:
    print("ERROR: Could not find Gemini call block. Check the file manually.")
    print("Searching for alternative markers...")
    idx = src.find('"contents": [{"role": "user"')
    if idx != -1:
        print(f"  Found Gemini payload at char {idx}")
        # Back up to find the start of this block
        block_start = src.rfind("\n    #", 0, idx)
        print(f"  Block likely starts at char {block_start}: {src[block_start:block_start+40]!r}")
    raise SystemExit(1)

# Find where the Gemini block ends (at _keyword_fallback or next comment section)
keyword_start = src.find("\n\n# ", gemini_start)
if keyword_start == -1:
    keyword_start = src.find("\ndef _keyword_fallback", gemini_start)
if keyword_start == -1:
    print("ERROR: Could not find end of Gemini block.")
    raise SystemExit(1)

old_gemini_block = src[gemini_start:keyword_start]
print(f"Found Gemini block ({len(old_gemini_block)} chars):")
print(f"  Starts: {old_gemini_block[:60]!r}")
print(f"  Ends:   {old_gemini_block[-60:]!r}")

new_claude_block = '''    # -- Claude fallback (Anthropic Haiku -- fires when Groq fails) ------------
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 300,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_content}],
                        "temperature": 0.7,
                    },
                    timeout=12.0,
                )
                r.raise_for_status()
                return r.json()["content"][0]["text"].strip()
        except Exception as _ce:
            logger.error(f"Claude fallback also failed: {_ce}")

'''

src = src[:gemini_start] + new_claude_block + src[keyword_start:]

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

# Verify
with open(path, "r") as f:
    check = f.read()

groq_present = "groq.com/openai/v1" in check
claude_present = "anthropic.com/v1/messages" in check
gemini_gone = "generativelanguage.googleapis.com" not in check
anthropic_key = "ANTHROPIC_API_KEY" in check

print()
print(f"Groq call present:       {groq_present}")
print(f"Claude fallback present: {claude_present}")
print(f"Gemini removed:          {gemini_gone}")
print(f"ANTHROPIC_API_KEY used:  {anthropic_key}")
print()
if groq_present and claude_present and gemini_gone:
    print("SUCCESS -- fallback chain is now: Groq -> Claude -> keyword")
else:
    print("WARNING -- check manually:")
    print("  grep -n 'groq.com\\|anthropic\\|googleapis' app/services/concierge/ai_concierge.py")
