#!/usr/bin/env python3
"""
export_demo_dashboard.py — write the demo console to a standalone HTML file.

Produces a single, self-contained .html (the fictitious company's data is
inlined) that opens directly in any browser — handy when the app is running on
a remote/ephemeral host you can't reach at localhost.

Usage:
  python scripts/export_demo_dashboard.py [output_path]    # default: demo_dashboard.html
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_db_session
from app.api.v1.endpoints.demo_dashboard import build_demo_payload, _template


async def main() -> None:
    async with get_db_session() as db:
        payload = await build_demo_payload(db)
    html = _template().replace("__DEMO_DATA__", json.dumps(payload))
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_dashboard.html")
    dest.write_text(html, encoding="utf-8")
    print(f"Wrote {dest} — {len(html)} bytes; stats={payload['stats']}")


if __name__ == "__main__":
    asyncio.run(main())
