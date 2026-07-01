from __future__ import annotations

from typing import Protocol


class PreviewToolUnavailableError(RuntimeError):
    """Required preview tool is not installed or not executable."""


class PreviewRenderError(RuntimeError):
    """Preview converter failed while rendering a source file."""


class PreviewRenderTimeoutError(PreviewRenderError):
    """Preview converter exceeded the configured timeout."""


class PdfPreviewConverter(Protocol):
    async def render_first_page_png(self, source: bytes) -> bytes:
        """Render the first PDF page to PNG bytes."""
