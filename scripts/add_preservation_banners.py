#!/usr/bin/env python3
"""
add_preservation_banners.py

Prepends a standardized preservation-status banner to the module-level
docstring of each future-feature concierge file. If the file already has
a module docstring, the banner is inserted INTO that docstring (preserving
the existing content underneath). If the file has no module docstring, a
new docstring containing just the banner is added as the first statement.

Idempotent: if the banner is already present, the file is left untouched.

Run from repo root:
    python scripts/add_preservation_banners.py

The list of target files is hard-coded below — it matches the Phase 2
Commit 3 brief exactly. Don't extend this list to other files without
updating the brief.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TARGET_FILES = [
    "app/services/concierge/dining_service.py",
    "app/services/concierge/event_planning_service.py",
    "app/services/concierge/bd_insight_service.py",
    "app/services/concierge/portfolio_availability_service.py",
    "app/services/concierge/market_brain.py",
    "app/services/concierge/market_source_adapters.py",
    "app/services/concierge/group_session.py",
    "app/services/concierge/guest_profile_service.py",
    "app/services/concierge/operator_learning.py",
    "app/services/concierge/escapia_unified.py",
    "app/services/concierge/maintenance_service.py",
]

BANNER = """PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved."""

# Distinctive marker used to detect whether the banner is already present.
# Matches the first line of BANNER; verify_phase2_transplant.sh greps the
# same string.
BANNER_MARKER = "PRESERVATION STATUS (post-Phase-1"


def add_banner_to_file(path: Path) -> tuple[bool, str]:
    """
    Add the preservation banner to one file.

    Returns (changed, message). `changed` is True if the file was
    modified, False if it was already up-to-date or could not be
    processed.
    """
    if not path.is_file():
        return False, f"missing: {path}"

    original = path.read_text(encoding="utf-8")
    if BANNER_MARKER in original:
        return False, f"already banner-tagged: {path}"

    lines = original.splitlines(keepends=True)
    # Skip past any leading comments, shebang, or coding declaration to
    # find where the module docstring would live. PEP 263 allows the
    # coding line on the first two lines; we look at up to the first 5
    # lines to find either the docstring or definitive "no docstring".
    insert_idx = 0
    for i, line in enumerate(lines[:5]):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            insert_idx = i + 1
            continue
        if not stripped:
            insert_idx = i + 1
            continue
        # First non-comment, non-blank line. Decide based on whether it
        # opens a docstring.
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Module docstring exists. Insert the banner inside it.
            return _insert_into_existing_docstring(path, lines, i)
        # First statement is code, not a docstring. Prepend a new
        # banner-only docstring before it.
        return _prepend_new_docstring(path, lines, i)

    # File is entirely comments/blank in the first 5 lines (very short
    # or unusual file). Append the banner at insert_idx as a new docstring.
    return _prepend_new_docstring(path, lines, insert_idx)


def _insert_into_existing_docstring(
    path: Path, lines: list[str], docstring_line_idx: int
) -> tuple[bool, str]:
    """Insert the banner into an existing module docstring."""
    opener_line = lines[docstring_line_idx]
    stripped = opener_line.lstrip()
    quote = '"""' if stripped.startswith('"""') else "'''"

    # Detect single-line docstring like `"""One line."""`.
    rest = stripped[3:]
    if quote in rest:
        # Single-line docstring. Expand it into multi-line and add the
        # banner.
        indent = opener_line[: len(opener_line) - len(stripped)]
        existing_content = rest.split(quote, 1)[0].strip()
        new_docstring = (
            f"{indent}{quote}\n"
            f"{indent}{BANNER}\n"
            f"\n"
            f"{indent}{existing_content}\n"
            f"{indent}{quote}\n"
        )
        new_lines = lines[:docstring_line_idx] + [new_docstring] + lines[docstring_line_idx + 1 :]
        path.write_text("".join(new_lines), encoding="utf-8")
        return True, f"single-line docstring expanded with banner: {path}"

    # Multi-line docstring. Insert the banner on the line AFTER the
    # opening quote (so the opener line is preserved, and the banner
    # becomes the first content of the docstring).
    indent = opener_line[: len(opener_line) - len(stripped)]
    banner_block_lines = [f"{indent}{line}\n" if line else "\n" for line in BANNER.splitlines()]
    banner_block_lines.append("\n")  # blank line separating banner from existing docstring content

    new_lines = (
        lines[: docstring_line_idx + 1]
        + banner_block_lines
        + lines[docstring_line_idx + 1 :]
    )
    path.write_text("".join(new_lines), encoding="utf-8")
    return True, f"banner prepended into existing docstring: {path}"


def _prepend_new_docstring(
    path: Path, lines: list[str], insert_idx: int
) -> tuple[bool, str]:
    """Add a new module docstring containing just the banner."""
    docstring = f'"""\n{BANNER}\n"""\n\n'
    new_lines = lines[:insert_idx] + [docstring] + lines[insert_idx:]
    path.write_text("".join(new_lines), encoding="utf-8")
    return True, f"new banner-only docstring added: {path}"


def main() -> int:
    changed = 0
    skipped = 0
    failed = 0
    for rel in TARGET_FILES:
        path = REPO_ROOT / rel
        try:
            did_change, message = add_banner_to_file(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL   {rel}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if did_change:
            print(f"  WROTE  {message}")
            changed += 1
        else:
            print(f"  SKIP   {message}")
            skipped += 1

    print()
    print(f"Banners added: {changed}")
    print(f"Already present: {skipped}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
