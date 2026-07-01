from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError

_TEXT_MIME_TYPES = {
    "application/csv",
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/yaml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/tab-separated-values",
    "text/xml",
}
_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".markdown",
    ".txt",
    ".tsv",
    ".xml",
    ".yaml",
    ".yml",
}
_PDF_MIME_TYPES = {"application/pdf"}
_PDF_EXTENSIONS = {".pdf"}
_DEFAULT_PDF_MAX_PAGES = 50


class TextExtractionError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TextExtractionContext:
    mime_type: str
    name: str


class TextExtractor(Protocol):
    def supports(self, context: TextExtractionContext) -> bool: ...

    def extract(self, content: bytes, context: TextExtractionContext) -> str: ...


class Utf8TextExtractor:
    def supports(self, context: TextExtractionContext) -> bool:
        if context.mime_type.startswith("text/") or context.mime_type in _TEXT_MIME_TYPES:
            return True
        normalized_name = context.name.casefold()
        return any(normalized_name.endswith(extension) for extension in _TEXT_EXTENSIONS)

    def extract(self, content: bytes, context: TextExtractionContext) -> str:
        try:
            return content.decode("utf-8-sig").replace("\x00", "")
        except UnicodeDecodeError as exc:
            raise TextExtractionError("decode_failed") from exc


class PdfTextExtractor:
    def __init__(self, *, max_pages: int = _DEFAULT_PDF_MAX_PAGES) -> None:
        self.max_pages = max_pages

    def supports(self, context: TextExtractionContext) -> bool:
        normalized_name = context.name.casefold()
        return context.mime_type in _PDF_MIME_TYPES or any(
            normalized_name.endswith(extension) for extension in _PDF_EXTENSIONS
        )

    def extract(self, content: bytes, context: TextExtractionContext) -> str:
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise TextExtractionError("pdf_encrypted")
            page_texts: list[str] = []
            for page_number, page in enumerate(reader.pages):
                if page_number >= self.max_pages:
                    break
                page_texts.append(page.extract_text() or "")
        except TextExtractionError:
            raise
        except (PdfReadError, UnicodeDecodeError, OSError, ValueError) as exc:
            raise TextExtractionError("decode_failed") from exc
        return "\n".join(text.strip() for text in page_texts if text.strip())


def default_text_extractors() -> list[TextExtractor]:
    return [Utf8TextExtractor(), PdfTextExtractor()]
