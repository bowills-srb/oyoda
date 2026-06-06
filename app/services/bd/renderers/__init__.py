"""
BD Renderers.

Transforms structured intelligence → presentation formats.

Renderers are DUMB:
- They format data
- They don't compute
- They don't make decisions
"""

from .pitchbook_pdf import (
    PitchBookPDFRenderer,
    PitchBookStyles,
    render_pitchbook_pdf,
)


__all__ = [
    "PitchBookPDFRenderer",
    "PitchBookStyles",
    "render_pitchbook_pdf",
]
