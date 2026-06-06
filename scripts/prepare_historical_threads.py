#!/usr/bin/env python3
"""
Prepare historical thread text for concierge imports.

Inputs:
- Labeled plain text thread with "Guest:" / "Host:" (or "Operator:") lines.
- Unlabeled plain text thread (alternating message blocks).

Outputs:
- payload_gaps_import.json            -> POST /api/v1/concierge/knowledge/gaps/import
- payload_global_faq_import.json      -> POST /api/v1/concierge/knowledge/global-faq/import
- payload_maintenance_events.json     -> POST /api/v1/concierge/maintenance/events (optional)
- summary.json

Optional:
- --post to send payloads directly to local API.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request


GUEST_PREFIXES = ("guest:", "traveler:", "renter:", "customer:")
HOST_PREFIXES = ("host:", "operator:", "manager:", "concierge:", "agent:")

GLOBAL_HINTS = (
    "check in",
    "check out",
    "checkout",
    "wifi",
    "internet",
    "password",
    "parking",
    "late checkout",
    "early check",
    "support",
    "urgent",
    "after hours",
    "pet",
    "refund",
    "cancellation",
    "cancel",
    "modify reservation",
)

MAINTENANCE_HINTS = (
    "broken",
    "not working",
    "issue",
    "problem",
    "dishwasher",
    "washer",
    "dryer",
    "bike",
    "bicycle",
    "chain",
    "ac",
    "air conditioning",
    "heat",
    "leak",
    "toilet",
    "sink",
    "door",
    "lock",
    "keypad",
)


@dataclass
class Turn:
    role: str
    text: str


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def parse_turns(text: str) -> List[Turn]:
    turns: List[Turn] = []
    current_role: Optional[str] = None
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_role, buffer
        if current_role and buffer:
            content = "\n".join(buffer).strip()
            if content:
                turns.append(Turn(role=current_role, text=content))
        current_role = None
        buffer = []

    for raw in text.splitlines():
        line = raw.rstrip()
        lower = line.lower().strip()
        if not lower:
            if buffer:
                buffer.append("")
            continue

        is_guest = any(lower.startswith(p) for p in GUEST_PREFIXES)
        is_host = any(lower.startswith(p) for p in HOST_PREFIXES)
        if is_guest or is_host:
            flush()
            current_role = "guest" if is_guest else "host"
            line = re.sub(r"^[A-Za-z ]+:\s*", "", line, count=1)
            buffer.append(normalize_line(line))
            continue

        if current_role:
            buffer.append(normalize_line(line))

    flush()
    return turns


def parse_unlabeled_turns(text: str, starts_with: str = "guest") -> List[Turn]:
    """
    Parse unlabeled logs by alternating speaker blocks.

    Each block is one or more non-empty lines separated by blank lines.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    turns: List[Turn] = []
    current = starts_with if starts_with in {"guest", "host"} else "guest"
    for block in blocks:
        clean = normalize_line(block.replace("\n", " "))
        if not clean:
            continue
        turns.append(Turn(role=current, text=clean))
        current = "host" if current == "guest" else "guest"
    return turns


def parse_turns_auto(text: str, starts_with: str = "guest") -> Tuple[List[Turn], str]:
    labeled = parse_turns(text)
    if labeled:
        return labeled, "labeled"
    unlabeled = parse_unlabeled_turns(text, starts_with=starts_with)
    if unlabeled:
        return unlabeled, "unlabeled_alternating"
    return [], "none"


def pair_qa(turns: List[Turn]) -> List[Tuple[str, Optional[str]]]:
    pairs: List[Tuple[str, Optional[str]]] = []
    i = 0
    while i < len(turns):
        t = turns[i]
        if t.role != "guest":
            i += 1
            continue
        question = t.text.strip()
        answer = None
        if i + 1 < len(turns) and turns[i + 1].role == "host":
            answer = turns[i + 1].text.strip()
            i += 2
        else:
            i += 1
        if question:
            pairs.append((question, answer))
    return pairs


def looks_global(question: str, global_mode: str) -> bool:
    if global_mode == "all":
        return True
    if global_mode == "none":
        return False
    q = question.lower()
    return any(h in q for h in GLOBAL_HINTS)


def looks_maintenance(question: str) -> bool:
    q = question.lower()
    tokens = set(re.findall(r"[a-z0-9]+", q))
    for hint in MAINTENANCE_HINTS:
        if " " in hint:
            if hint in q:
                return True
        elif hint in tokens:
            return True
    return False


def build_payloads(
    pairs: List[Tuple[str, Optional[str]]],
    property_external_id: Optional[str],
    stage: str,
    global_mode: str,
    source: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    gaps_records: List[Dict[str, Any]] = []
    global_records: List[Dict[str, Any]] = []
    maintenance_records: List[Dict[str, Any]] = []
    seen_global: set[str] = set()

    for question, answer in pairs:
        if looks_maintenance(question):
            item: Dict[str, Any] = {
                "issue_text": question,
                "source": source,
                "metadata": {
                    "origin": "historical_thread",
                    "stage": stage,
                },
            }
            if property_external_id:
                item["property_external_id"] = property_external_id
            if answer:
                item["notes"] = f"Historical host response: {answer}"
            maintenance_records.append(item)

        is_global = looks_global(question, global_mode)
        if answer:
            if is_global:
                key = re.sub(r"\s+", " ", question.strip().lower())
                if key not in seen_global:
                    seen_global.add(key)
                    global_records.append(
                        {
                            "question_text": question,
                            "answer_text": answer,
                            "source": source,
                            "tags": ["historical_thread"],
                            "metadata": {"stage": stage},
                        }
                    )
            else:
                row: Dict[str, Any] = {
                    "question_text": question,
                    "answer_text": answer,
                    "stage": stage,
                    "source": source,
                    "channel": "text",
                }
                if property_external_id:
                    row["property_external_id"] = property_external_id
                gaps_records.append(row)
        else:
            row = {
                "question_text": question,
                "stage": stage,
                "source": source,
                "channel": "text",
            }
            if property_external_id:
                row["property_external_id"] = property_external_id
            gaps_records.append(row)

    gaps_payload = {
        "apply_to_similar_properties": True,
        "records": gaps_records,
    }
    global_payload = {
        "records": global_records,
    }
    maintenance_payload = {
        "records": maintenance_records,
    }
    summary = {
        "total_pairs": len(pairs),
        "gaps_records": len(gaps_records),
        "global_faq_records": len(global_records),
        "maintenance_records": len(maintenance_records),
        "property_external_id": property_external_id,
        "stage": stage,
        "global_mode": global_mode,
    }
    return gaps_payload, global_payload, maintenance_payload, summary


def post_json(url: str, payload: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Company-Id": company_id,
        },
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} posting to {url}: {detail}") from exc


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    text = input_path.read_text(encoding="utf-8")
    if args.parser_mode == "labeled":
        turns = parse_turns(text)
        parser_mode_used = "labeled"
    elif args.parser_mode == "unlabeled":
        turns = parse_unlabeled_turns(text, starts_with=args.starts_with)
        parser_mode_used = "unlabeled_alternating"
    else:
        turns, parser_mode_used = parse_turns_auto(text, starts_with=args.starts_with)

    pairs = pair_qa(turns)
    if not pairs:
        print(
            "No guest/host pairs found. "
            "Use labeled lines (Guest:/Host:) or set --parser-mode unlabeled."
        )
        return 1

    gaps_payload, global_payload, maintenance_payload, summary = build_payloads(
        pairs=pairs,
        property_external_id=args.property_external_id,
        stage=args.stage,
        global_mode=args.global_mode,
        source=args.source,
    )
    summary["parser_mode_used"] = parser_mode_used

    gaps_path = out_dir / "payload_gaps_import.json"
    global_path = out_dir / "payload_global_faq_import.json"
    maintenance_path = out_dir / "payload_maintenance_events.json"
    summary_path = out_dir / "summary.json"

    gaps_path.write_text(json.dumps(gaps_payload, indent=2), encoding="utf-8")
    global_path.write_text(json.dumps(global_payload, indent=2), encoding="utf-8")
    maintenance_path.write_text(json.dumps(maintenance_payload, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {gaps_path}")
    print(f"Wrote {global_path}")
    print(f"Wrote {maintenance_path}")
    print(f"Wrote {summary_path}")
    print(json.dumps(summary, indent=2))

    if args.post:
        if not args.company_id:
            print("--company-id is required when using --post")
            return 1
        base_url = args.api_base.rstrip("/")
        posted: Dict[str, Any] = {}
        if gaps_payload["records"]:
            posted["gaps_import"] = post_json(
                f"{base_url}/api/v1/concierge/knowledge/gaps/import",
                gaps_payload,
                args.company_id,
            )
        if global_payload["records"]:
            posted["global_faq_import"] = post_json(
                f"{base_url}/api/v1/concierge/knowledge/global-faq/import",
                global_payload,
                args.company_id,
            )
        if args.post_maintenance and maintenance_payload["records"]:
            maintenance_results: List[Dict[str, Any]] = []
            for record in maintenance_payload["records"]:
                maintenance_results.append(
                    post_json(
                        f"{base_url}/api/v1/concierge/maintenance/events",
                        record,
                        args.company_id,
                    )
                )
            posted["maintenance_events"] = {
                "created": len(maintenance_results),
                "items": maintenance_results[:5],
            }
        print(json.dumps({"posted": posted}, indent=2))

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare historical threads for concierge import.")
    parser.add_argument("--input", required=True, help="Path to plain-text thread file.")
    parser.add_argument(
        "--output-dir",
        default="scripts/output/historical_threads",
        help="Output directory for generated payload files.",
    )
    parser.add_argument(
        "--property-external-id",
        default=None,
        help="Property unit code (omit for fully generic/global batches).",
    )
    parser.add_argument(
        "--stage",
        default="in_stay",
        choices=["pre_booking", "booked", "in_stay", "post_stay"],
        help="Default stage for imported records.",
    )
    parser.add_argument(
        "--global-mode",
        default="auto",
        choices=["auto", "all", "none"],
        help="How to route answered questions to global FAQ.",
    )
    parser.add_argument(
        "--source",
        default="historical_thread",
        help="Source tag stored on created records.",
    )
    parser.add_argument(
        "--parser-mode",
        default="auto",
        choices=["auto", "labeled", "unlabeled"],
        help="Parse strategy for thread text.",
    )
    parser.add_argument(
        "--starts-with",
        default="guest",
        choices=["guest", "host"],
        help="Starting speaker for unlabeled parser mode.",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post generated payloads to API after writing files.",
    )
    parser.add_argument(
        "--post-maintenance",
        action="store_true",
        help="When used with --post, also create maintenance events from detected issue questions.",
    )
    parser.add_argument("--company-id", default=None, help="Tenant/company UUID for API post mode.")
    parser.add_argument("--api-base", default="http://localhost:8000", help="API base URL.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
