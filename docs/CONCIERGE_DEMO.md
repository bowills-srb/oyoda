# Beach Habitats Guest Concierge System

## Quick Start for Demo

### 1. Start the Services
```bash
# Start database and redis
docker-compose up -d postgres redis

# Run migrations (creates the concierge tables)
alembic -c alembic.ini upgrade head

# Start the API server
uvicorn app.main:app --reload --port 8000
```

For hosted deploys, prefer setting `ALEMBIC_DATABASE_URL` separately from
`DATABASE_URL` so schema upgrades are not coupled to the runtime pooler path.

### 2. Create a Test Guest Session
```bash
curl -X POST http://localhost:8000/api/v1/operator/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "property_code": "sea-la-vie",
    "guest_first_name": "Sarah",
    "guest_phone": "+15551234567",
    "guest_email": "sarah@example.com",
    "check_in": "2026-03-15",
    "check_out": "2026-03-22",
    "num_guests": 4
  }'
```

Response will include a token like `gh_abc123xyz...`

### 3. Open the Guest Concierge
Open in browser: `http://localhost:8000/c/{token}`

This is what guests see when they click the SMS link.

---

## What the Guest Experiences

### Welcome Message (sent on booking)
```
Hi Sarah! 🏖️

Welcome to Sea La Vie! I'm Coral, your Beach Habitats concierge.

I'm here to help make your stay as enjoyable as possible - from booking 
beach chairs to finding the best local restaurants.

📅 Quick tip for your March trip: A few things book up fast during this 
time - especially beach chair setups, fishing charters, and popular 
restaurants. Happy to help you get those sorted whenever you're ready!

Is there anything specific you'd like help with before your arrival? 
Golf tee times, fishing excursions, beach rentals, restaurant 
recommendations - just let me know!
```

### Quick Answers (instant, no AI needed)
- **WiFi**: "Your WiFi network is SeaLaVie-Guest, password: beach2026"
- **Door code**: "Your door code will be sent the morning of check-in"
- **Checkout**: "Checkout is at 10:00 AM"
- **Pool heat**: "$50/day, 48 hours notice needed"
- **Beach conditions**: Live flag status from Walton County

### Activity Recommendations (curated local providers)
When guest asks "I need beach chairs":
```
Beach chair and umbrella setups are the way to go on 30A! Here are the 
local providers I recommend:

**1. La Dolce Vita Beach Services**
   Premium beach setups - chairs, umbrellas, cabanas. Most popular on 30A.
   📞 (850) 267-1444
   🌐 https://www.ldvbeach.com

**2. Beach Chair Guys**
   Reliable beach chair and umbrella rentals. Good availability.
   📞 (850) 419-4862

⚠️ Heads up: During July, these book up fast! I'd recommend reaching out soon.
```

### Restaurant Recommendations (local-first)
When guest asks "where should we eat":
- Prioritizes local/family-owned businesses
- Chains listed last as fallbacks
- Categories: seafood, steakhouse, Italian, Mexican, sushi, coffee, brunch, etc.

### Extend Stay Offer (day before checkout)
If no next guest is arriving:
```
Hi Sarah! 🌟

Not ready to leave Sea La Vie? Good news - we don't have anyone 
arriving tomorrow!

🎁 Special offer: 10% off if you'd like to stay Saturday, March 21.

Reply YES if interested and I'll take care of the details!
```

---

## Features

| Feature | Status | Notes |
|---------|--------|-------|
| Mobile chat interface | ✅ Ready | `/c/{token}` |
| Voice input | ✅ Ready | Tap microphone |
| Quick answers | ✅ Ready | WiFi, codes, parking, etc. |
| Beach flag conditions | ✅ Ready | Live scraping |
| Restaurant recs | ✅ Ready | Local-first ordering |
| Activity providers | ✅ Ready | Beach chairs, fishing, golf, etc. |
| Welcome message | ✅ Ready | Customized per season |
| Pool heat | ✅ Ready | $50/day messaging |
| Extend stay offer | ✅ Ready | 10% off, checks for next booking |
| SMS delivery | ✅ Ready | Requires Twilio config |
| Database persistence | ✅ Ready | Sessions, messages, journeys |
| Operator dashboard | 🔧 API only | Needs frontend |
| Owner dashboard | 🔧 API only | Needs frontend |

---

## API Endpoints

### Operator (Property Manager)
```
POST /api/v1/operator/sessions              # Create guest session
GET  /api/v1/operator/sessions              # List all sessions
GET  /api/v1/operator/sessions/{token}      # Get session details
POST /api/v1/operator/sessions/{token}/send-link  # Send SMS to guest
GET  /api/v1/operator/sessions/{token}/journey    # View guest journey
```

### Owner Dashboard
```
POST /api/v1/owner/signup                   # Owner signup
GET  /api/v1/owner/dashboard                # Dashboard overview
GET  /api/v1/owner/properties               # List properties
PUT  /api/v1/owner/properties/{id}/config   # Configure property
GET  /api/v1/owner/properties/{id}/analytics # View analytics
GET  /api/v1/owner/properties/{id}/extend-stay-opportunities  # Find upsell opportunities
```

### Guest Mobile
```
GET  /c/{token}                             # Mobile concierge UI
POST /api/v1/mobile/{token}/chat            # Send message
GET  /api/v1/mobile/{token}/messages        # Get conversation history
```

---

## Configuration Needed

### .env file
```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/beach_habitats

# SMS (Twilio)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+15551234567

# AI (for complex questions)
ANTHROPIC_API_KEY=your_key
GEMINI_API_KEY=your_key

# Voice (optional)
DEEPGRAM_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
```

---

## Feedback Needed from Owner

1. **Welcome message tone** - Is "Coral" the right concierge name?
2. **Activity providers** - Are the listed providers correct? Any to add/remove?
3. **Restaurant list** - Any favorites missing? Any to remove?
4. **Extend stay discount** - Is 10% right? Should it vary by season?
5. **Pool heat pricing** - Is $50/day correct?
6. **Check-in/out times** - What are the standard times?
7. **Beach access** - How do wristbands work at different properties?
8. **SMS timing** - When should welcome message be sent? (booking confirmation? X days before?)

---

## Run the Demo Script
```bash
python scripts/demo_concierge.py
```

This shows all the message templates and provider lists without needing the full system running.
