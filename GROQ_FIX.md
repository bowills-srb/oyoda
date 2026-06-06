# Groq Fix — Manual Instructions

The `_generate_response` function in `ai_concierge.py` currently checks for
`GOOGLE_API_KEY` or `GEMINI_API_KEY`. It needs to check `GROQ_API_KEY` first.

## Option A: Apply via terminal (fastest)

```bash
cd ~/Downloads/oyvoda
python3 - << 'EOF'
import re

path = "app/services/concierge/ai_concierge.py"
with open(path, "r") as f:
    src = f.read()

# Find and replace the api_key line
old = 'api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")\n    if not api_key:'
new = 'groq_key = os.getenv("GROQ_API_KEY", "")\n    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")\n    if not groq_key and not gemini_key:'

src = src.replace(old, new)

# Fix the api_key reference in the Gemini call
src = src.replace(
    'f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"',
    'f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_key}"'
)

# Fix the system prompt to be warmer and use groq
old_prompt = '''    system_prompt = (
        f"You are {concierge_name} {concierge_emoji}, the personal beach concierge for {guest_name} staying at {property_name}.\\n"
        f"Style: warm, brief (2 sentences max unless detail is needed), helpful local friend. {eq_hint}\\n"
        f"Context: {phase_hint}\\n"
        + (f"Guest history: {repeat_snippet}\\n" if repeat_snippet else "")
        + f"Escalations: direct to {support_phone}."
    )'''

new_prompt = '''    system_prompt = (
        f"You are {concierge_name} \\U0001f41a, personal concierge for {guest_name} at {property_name}.\\n"
        f"Voice: warm, specific, conversational \\u2014 like a knowledgeable local friend texting, never robotic.\\n"
        f"Always use real names for places. Never say \\'I don\\'t have that information\\' \\u2014 use your local knowledge.\\n"
        f"Give 2-3 specific named options when asked for recommendations. End with an open question.\\n"
        f"When a guest picks something, proactively offer the next logical thing without waiting to be asked.\\n"
        f"{phase_hint} {eq_hint}\\n"
        + (f"Guest history: {repeat_snippet}\\n" if repeat_snippet else "")
        + f"Emergencies: {support_phone}."
    )'''

src = src.replace(old_prompt, new_prompt)

# Add Groq call before Gemini call
old_gemini = '''    # ── Gemini call ───────────────────────────────────────────────────────────
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 250,   # Tighter cap than before (was 300)
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_key}",
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    except httpx.TimeoutException:
        logger.error("Gemini timeout")
        return _keyword_fallback(message, property_facts or property_context, guest_name)
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return _keyword_fallback(message, property_facts or property_context, guest_name)'''

new_calls = '''    # ── Groq call (primary) ──────────────────────────────────────────────────
    if groq_key:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
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
        except Exception as e:
            logger.warning(f"Groq legacy path failed: {e}")

    # ── Gemini fallback ───────────────────────────────────────────────────────
    if gemini_key:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_key}",
                    json={
                        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
                        "systemInstruction": {"parts": [{"text": system_prompt}]},
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300},
                    },
                    timeout=10.0,
                )
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logger.error(f"Gemini fallback also failed: {e}")

    return _keyword_fallback(message, property_facts or property_context, guest_name)'''

src = src.replace(old_gemini, new_calls)

with open(path, "w") as f:
    f.write(src)

print("Done. Verify with: grep -n 'GROQ_API_KEY\\|groq_key\\|Groq call' app/services/concierge/ai_concierge.py")
EOF
```

## Option B: Add env var to bypass entirely

Since `concierge_intelligence.py` already uses Groq correctly and is the
PRIMARY path (called first at Step 7), once it deploys successfully the
legacy `_generate_response` only runs as a fallback when the intelligence
layer crashes. 

For now, the fastest fix is:
**In Railway, make sure GROQ_API_KEY is set and starts with `gsk_`**

The intelligence layer (concierge_intelligence.py) will use it directly
once the current Railway build completes.

## Railway Variables Checklist

Set these now if not already done:

| Variable | Value |
|---|---|
| GROQ_API_KEY | gsk_... (your Groq key) |
| ANTHROPIC_API_KEY | sk-ant-... (just added) |
| JWT_SECRET | (already added) |
| ENVIRONMENT | production |
| DATABASE_URL | postgresql+asyncpg://postgres.mskazxakxowcggxmkmrp:PASSWORD@aws-1-us-east-1.pooler.supabase.com:6543/postgres |
