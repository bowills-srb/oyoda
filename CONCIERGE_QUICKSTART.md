# Beach Habitats Guest Concierge - Quick Start

## Start Demo in 2 Minutes

### Step 1: Start the Server
```bash
cd /Users/dhuntermckenzie/Downloads/STR-Beach_Habitats
source .venv/bin/activate  # or venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### Step 2: Run the Test Script
In another terminal:
```bash
cd /Users/dhuntermckenzie/Downloads/STR-Beach_Habitats
python test_concierge.py
```

This creates a test session and shows you the guest URL.

### Step 3: Open Guest Interface
The test script will output a URL like:
```
http://localhost:8000/c/gh_AbCdEfGh
```

Open this on your phone or in a browser to see what guests see.

---

## What to Show the Owner

### Guest Experience
1. **Welcome message** - Introduces Coral with property name
2. **Quick buttons** - WiFi, Door Code, Restaurants, Checkout
3. **Voice input** - Tap microphone to speak
4. **Beach conditions** - Live flag status (during stay)

### Try These Queries
- "What's the WiFi password?" → Instant answer
- "Beach chair rentals" → Local provider list (La Dolce Vita first)
- "Restaurant recommendations" → Local-first suggestions
- "Looking for a good burger" → Pickles, Red Bar, etc.
- "Golf tee times" → Camp Creek, Santa Rosa, Emerald Bay
- "Is the pool heated?" → Yes, $50/day, 48hr notice
- "Fishing charter" → Local charter options

### Key Features to Highlight
1. **Local-first recommendations** - Chains listed last as fallbacks
2. **Pool heat pricing** - $50/day clearly stated
3. **Beach chairs booking ahead** - 60 days for peak season
4. **Extend stay offer** - 10% off if no next guest (not in demo yet)

---

## For Production: Environment Setup

Add to `.env`:
```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/beach_habitats

# Twilio SMS
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+1234567890

# SendGrid Email
SENDGRID_API_KEY=your_key
SENDGRID_FROM_EMAIL=concierge@beachhabitats.com

# Already have
GROQ_API_KEY=your_groq_api_key
```

## Database Migration (When Ready)

```bash
# Generate migration for new tables
alembic revision --autogenerate -m "add_concierge_sessions"

# Apply migration
alembic upgrade head
```

New tables added:
- `concierge_sessions` - Guest sessions
- `concierge_journey_activities` - What they've discussed
- `concierge_message_logs` - Conversation history
- `concierge_notifications` - SMS/email tracking
- `concierge_escalations` - Help requests

---

## API Endpoints

### Operator (Property Manager)
```
POST /api/v1/operator/sessions              # Create guest session
GET  /api/v1/operator/sessions              # List all sessions
GET  /api/v1/operator/sessions/{token}      # Get session details
POST /api/v1/operator/sessions/{token}/send-link  # Send SMS/email
GET  /api/v1/operator/sessions/{token}/journey    # View journey status
```

### Guest (Mobile Interface)
```
GET  /c/{token}                             # Mobile chat interface
POST /api/v1/mobile/{token}/chat            # Send message
POST /api/v1/mobile/{token}/feedback        # Submit rating
POST /api/v1/mobile/{token}/escalate        # Request human help
```

---

## Current Status

### ✅ Working Now
- Mobile chat interface with voice
- Restaurant recommendations (local-first)
- Activity providers (beach chairs, fishing, golf, bikes)
- Quick answers (WiFi, codes, checkout, pool heat)
- Beach flag conditions
- Welcome message generation
- Extend stay offer text generation

### 🔄 In Progress
- Database persistence (tables created, needs migration)
- SMS delivery (code ready, needs Twilio credentials)
- Extend stay eligibility check (needs booking table query)

### 📋 Next Steps
1. Run database migration
2. Add Twilio credentials
3. Connect to Escapia for auto-sync
4. Build operator dashboard frontend
