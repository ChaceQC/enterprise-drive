from __future__ import annotations

from typing import Protocol


class PreviewUnsupportedError(RuntimeError):
    """Preview source or generated output is outside supported policy."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class PreviewToolUnavailableError(RuntimeError):
    """Required preview tool is not installed or not executable."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class PreviewRenderError(RuntimeError):
    """Preview converter failed while rendering a source file."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class PreviewRenderTimeoutError(PreviewRenderError):
    """Preview converter exceeded the configured timeout."""


class PdfPreviewConverter(Protocol):
    async def render_first_page_png(self, source: bytes) -> bytes:
        """Render the first PDF page to PNG bytes."""


class OfficePreviewConverter(Protocol):
    async def convert_to_pdf(self, source: bytes, *, file_extension: str) -> bytes:
        """Convert an office document to PDF bytes."""
