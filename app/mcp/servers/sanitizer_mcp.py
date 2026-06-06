"""
Sanitizer MCP Server — "Lock 2" of the Three-Lock Security System

This is the PII Redaction layer Gemini described.
ALL data that flows from external sources INTO the LLM's context
MUST pass through this server first.

What it scrubs:
  - Guest phone numbers
  - Guest email addresses
  - Credit card / payment tokens
  - SSNs and ID numbers
  - Private owner notes flagged with [PRIVATE]
  - Full addresses when only city/region is needed

Why this is an MCP (not a middleware):
  By making it an MCP, agents actively CALL it before storing anything
  to long-term memory or injecting into another agent's context.
  This creates an auditable, explicit sanitization step vs a silent middleware.

Tools exposed:
  sanitize_text(text)              → cleaned text + redaction report
  sanitize_guest_record(record)    → cleaned guest dict
  sanitize_booking_data(data)      → cleaned booking dict
  check_pii(text)                  → detect (but don't redact) PII — for alerts
"""

import logging
import re
from typing import Any, Dict, List, Tuple

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Redaction Patterns
# ─────────────────────────────────────────────────────────────────────────────

_PATTERNS: List[Tuple[str, str, str]] = [
    # (name, regex, replacement)
    ("phone_us",          r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",         "[PHONE]"),
    ("phone_intl",        r"\+\d{1,3}[\s.-]?\(?\d{1,4}\)?[\s.-]?\d{1,9}[\s.-]?\d{1,9}",    "[PHONE]"),
    ("email",             r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",          "[EMAIL]"),
    ("credit_card",       r"\b(?:\d{4}[-\s]?){3}\d{4}\b",                                    "[CARD]"),
    ("ssn",               r"\b\d{3}-\d{2}-\d{4}\b",                                          "[SSN]"),
    ("passport",          r"\b[A-Z]{1,2}\d{6,9}\b",                                          "[PASSPORT]"),
    ("private_note",      r"\[PRIVATE\].*?(\[/PRIVATE\]|$)",                                  "[PRIVATE NOTE REDACTED]"),
    ("door_code_raw",     r"\bdoor\s*code[:\s]+\d{4,8}\b",                                   "door code: [CODE]"),
    ("wifi_password_raw", r"\b(wifi|wi-fi)\s*(password|pw|pass)[:\s]+\S+",                   "wifi password: [PASSWORD]"),
]

_COMPILED = [(name, re.compile(pattern, re.IGNORECASE | re.DOTALL), repl)
             for name, pattern, repl in _PATTERNS]


class SanitizerMCPServer(MCPServer):
    """
    PII Redaction MCP — runs 100% in-process, zero tokens, zero latency.

    This is the cheapest MCP to operate because it's pure Python regex.
    At 100 operators × 1000 guest interactions/day = 100,000 sanitizations/day,
    this saves ~$50-200/day vs sending raw data to an LLM for cleaning.
    """

    server_name = "sanitizer"
    server_description = "PII redaction — strips phones, emails, card numbers before LLM sees data"

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="sanitize_text",
                description="Remove PII from any freeform text string",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "report_redactions": {"type": "boolean", "default": False},
                    },
                    "required": ["text"],
                },
                returns="Dict: {clean_text: str, redaction_count: int, types_found: [str]}",
                category="security",
            ),
            MCPTool(
                name="sanitize_guest_record",
                description="Remove PII from a guest record dict (keeps name, strips contact details)",
                parameters={
                    "type": "object",
                    "properties": {
                        "record": {"type": "object"},
                        "keep_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Fields to always keep even if they contain PII",
                        },
                    },
                    "required": ["record"],
                },
                returns="Sanitized guest record dict",
                category="security",
            ),
            MCPTool(
                name="check_pii",
                description="Detect PII in text WITHOUT redacting it — for alerts and logging",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
                returns="Dict: {has_pii: bool, types_found: [str], count: int}",
                category="security",
            ),
            MCPTool(
                name="sanitize_owner_notes",
                description="Strip private owner notes before returning to guest-facing agents",
                parameters={
                    "type": "object",
                    "properties": {
                        "notes": {"type": "string"},
                    },
                    "required": ["notes"],
                },
                returns="Dict: {clean_notes: str, private_sections_removed: int}",
                category="security",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        # Note: operator_id is logged but sanitizer doesn't need it for logic
        if tool_name == "sanitize_text":
            return self._sanitize_text(operator_id, params)
        elif tool_name == "sanitize_guest_record":
            return self._sanitize_guest_record(operator_id, params)
        elif tool_name == "check_pii":
            return self._check_pii(operator_id, params)
        elif tool_name == "sanitize_owner_notes":
            return self._sanitize_owner_notes(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    # ─────────────────────────────────────────
    # Tool implementations (all sync, wrapped in MCPResult)
    # ─────────────────────────────────────────

    def _sanitize_text(self, operator_id: str, params: Dict) -> MCPResult:
        text = params["text"]
        report = params.get("report_redactions", False)

        clean, types_found, count = _redact(text)

        return MCPResult(
            success=True,
            data={
                "clean_text": clean,
                "redaction_count": count,
                "types_found": types_found,
                **({"original_length": len(text), "clean_length": len(clean)} if report else {}),
            },
            message=f"Redacted {count} PII instances ({', '.join(types_found) or 'none'})",
        )

    def _sanitize_guest_record(self, operator_id: str, params: Dict) -> MCPResult:
        record = params["record"]
        keep_fields = set(params.get("keep_fields", []))

        # Fields that are always safe to keep
        SAFE_FIELDS = {
            "guest_id", "booking_id", "first_name", "last_name",
            "nationality", "language", "arrival_date", "departure_date",
            "nights", "adults", "children", "platform",
            "has_dog", "pet_friendly_required",  # Preference flags, not PII
        }

        # Fields that should always be redacted regardless of value
        PII_FIELDS = {
            "phone", "phone_number", "email", "email_address",
            "credit_card", "card_number", "payment_token",
            "ssn", "passport_number", "id_number",
            "full_address", "home_address",
        }

        clean_record = {}
        redacted_fields = []

        for key, value in record.items():
            if key in keep_fields or key in SAFE_FIELDS:
                clean_record[key] = value
            elif key in PII_FIELDS:
                clean_record[key] = "[REDACTED]"
                redacted_fields.append(key)
            elif isinstance(value, str):
                cleaned, _, count = _redact(value)
                clean_record[key] = cleaned
                if count > 0:
                    redacted_fields.append(key)
            else:
                clean_record[key] = value

        return MCPResult(
            success=True,
            data={"record": clean_record, "redacted_fields": redacted_fields},
            message=f"Guest record sanitized ({len(redacted_fields)} fields redacted)",
        )

    def _check_pii(self, operator_id: str, params: Dict) -> MCPResult:
        text = params["text"]
        _, types_found, count = _redact(text)

        return MCPResult(
            success=True,
            data={
                "has_pii": count > 0,
                "types_found": types_found,
                "count": count,
            },
            message=f"PII {'detected' if count > 0 else 'not detected'}: {', '.join(types_found) or 'clean'}",
        )

    def _sanitize_owner_notes(self, operator_id: str, params: Dict) -> MCPResult:
        notes = params["notes"]

        # Count [PRIVATE] sections before redaction
        private_sections = len(re.findall(r"\[PRIVATE\]", notes, re.IGNORECASE))

        clean, types_found, count = _redact(notes)

        return MCPResult(
            success=True,
            data={
                "clean_notes": clean,
                "private_sections_removed": private_sections,
                "additional_pii_redacted": count - private_sections,
            },
            message=f"Owner notes sanitized: {private_sections} private sections, {count} total redactions",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Core redaction function (pure Python, zero deps beyond re)
# ─────────────────────────────────────────────────────────────────────────────

def _redact(text: str) -> Tuple[str, List[str], int]:
    """
    Apply all redaction patterns to text.

    Returns:
        (clean_text, types_found, total_redaction_count)
    """
    clean = text
    types_found = []
    count = 0

    for name, pattern, replacement in _COMPILED:
        new_text, n = pattern.subn(replacement, clean)
        if n > 0:
            types_found.append(name)
            count += n
            clean = new_text

    return clean, list(set(types_found)), count
