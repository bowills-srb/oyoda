# Beach Habitats — Frontend Demo

A fully self-contained marketing site and interactive demo for the Beach Habitats AI Concierge Platform.

## Running

No build step required. Open directly in a browser:

```bash
open frontend/demo/index.html
```

Or serve it locally (avoids any CORS issues with file inputs):

```bash
cd frontend/demo
python3 -m http.server 8080
# → http://localhost:8080
```

## What's included

- **Home** — Marketing landing page with stats and feature grid
- **Live Demo** — Interactive demo with two tabs:
  - 🏖️ **Guest UI** — White-label chat interface with logo upload and live customization
  - 📊 **Operator Dashboard** — Full analytics dashboard (8 sections)
- **For Operators** — Onboarding flow walkthrough
- **Pricing** — Three-tier pricing with monthly/annual toggle
- **Sign Up** — 3-step onboarding form

## Tech

- React 18 (CDN)
- Recharts 2.12 (CDN)
- Babel Standalone (in-browser JSX transpilation)
- Google Fonts: Playfair Display + Inter
- Zero dependencies, zero build step

## Notes

- All data is mock/static — no backend calls
- Logo upload works via FileReader API (local only)
- Production version will wire the guest UI to `ai_concierge.py` via the FastAPI backend
