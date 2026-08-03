from __future__ import annotations

import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.modules.search.extractors import (
    OcrTextEngine,
    OfficeDocumentConverter,
    TextExtractionContext,
    TextExtractionError,
)

_OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".odp",
    ".ods",
    ".odt",
    ".ppt",
    ".pptx",
    ".rtf",
    ".xls",
    ".xlsx",
}
_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


class TesseractOcrEngine(OcrTextEngine):
    def __init__(
        self,
        *,
        command: str = "tesseract",
        pdf_command: str = "pdftoppm",
        languages: str = "eng+chi_sim",
        page_segmentation_mode: int = 3,
        max_pages: int = 20,
        pdf_dpi: int = 144,
        max_pixels: int = 100_000_000,
        max_rendered_bytes: int = 100 * 1024 * 1024,
        timeout_seconds: int = 60,
        max_output_chars: int = 1_000_000,
    ) -> None:
        self.command = command
        self.pdf_command = pdf_command
        self.languages = languages
        self.page_segmentation_mode = page_segmentation_mode
        self.max_pages = max_pages
        self.pdf_dpi = pdf_dpi
        self.max_pixels = max_pixels
        self.max_rendered_bytes = max_rendered_bytes
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def extract_image(self, content: bytes, context: TextExtractionContext) -> str:
        self._require_command(self.command)
        extension = _safe_extension(context.name, allowed=_IMAGE_EXTENSIONS, fallback=".png")
        with tempfile.TemporaryDirectory(prefix="drive-ocr-image-") as temp_dir:
            input_path = Path(temp_dir) / f"source{extension}"
            input_path.write_bytes(content)
            self._validate_image_limits([input_path])
            return self._run_tesseract(input_path)

    def extract_pdf(
        self,
        content: bytes,
        context: TextExtractionContext,
        *,
        max_pages: int,
    ) -> str:
        del context
        self._require_command(self.command)
        self._require_command(self.pdf_command)
        bounded_pages = min(max_pages, self.max_pages)
        with tempfile.TemporaryDirectory(prefix="drive-ocr-pdf-") as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "source.pdf"
            output_prefix = temp_path / "page"
            source_path.write_bytes(content)
            self._run(
                [
                    self.pdf_command,
                    "-f",
                    "1",
                    "-l",
                    str(bounded_pages),
                    "-r",
                    str(self.pdf_dpi),
                    "-png",
                    str(source_path),
                    str(output_prefix),
                ],
                reason="ocr_pdf_render_failed",
            )
            page_paths = sorted(temp_path.glob("page-*.png"), key=_rendered_page_number)
            if not page_paths:
                raise TextExtractionError("ocr_pdf_render_failed")
            self._validate_image_limits(page_paths)
            texts = [self._run_tesseract(page_path) for page_path in page_paths]
            return self._bounded_text("\n".join(text for text in texts if text))

    def _run_tesseract(self, input_path: Path) -> str:
        completed = self._run(
            [
                self.command,
                str(input_path),
                "stdout",
                "-l",
                self.languages,
                "--psm",
                str(self.page_segmentation_mode),
            ],
            reason="ocr_failed",
        )
        return self._bounded_text(completed.stdout.decode("utf-8", errors="replace").strip())

    def _validate_image_limits(self, paths: list[Path]) -> None:
        total_bytes = sum(path.stat().st_size for path in paths)
        if total_bytes > self.max_rendered_bytes:
            raise TextExtractionError("ocr_rendered_bytes_exceeded", status="skipped")
        total_pixels = 0
        try:
            for path in paths:
                with Image.open(path) as image:
                    total_pixels += image.width * image.height
                    if total_pixels > self.max_pixels:
                        raise TextExtractionError("ocr_pixels_exceeded", status="skipped")
        except (UnidentifiedImageError, OSError) as exc:
            raise TextExtractionError("ocr_image_decode_failed") from exc

    def _bounded_text(self, text: str) -> str:
        if len(text) > self.max_output_chars:
            raise TextExtractionError("ocr_text_too_large", status="skipped")
        return text

    def _require_command(self, command: str) -> None:
        if shutil.which(command) is None:
            raise TextExtractionError("ocr_tool_unavailable", status="skipped")

    def _run(self, args: list[str], *, reason: str) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(  # nosec B603
                args,
                check=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise TextExtractionError("ocr_timeout") from exc
        except subprocess.CalledProcessError as exc:
            raise TextExtractionError(reason) from exc
        except OSError as exc:
            raise TextExtractionError("ocr_tool_unavailable", status="skipped") from exc


class LibreOfficeSearchConverter(OfficeDocumentConverter):
    def __init__(
        self,
        *,
        command: str = "soffice",
        timeout_seconds: int = 60,
        max_pdf_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.max_pdf_bytes = max_pdf_bytes

    def convert_to_pdf(self, content: bytes, context: TextExtractionContext) -> bytes:
        if shutil.which(self.command) is None:
            raise TextExtractionError("office_tool_unavailable", status="skipped")
        extension = _safe_extension(
            context.name,
            allowed=_OFFICE_EXTENSIONS,
            fallback=None,
        )
        if extension is None:
            raise TextExtractionError("office_format_unsupported", status="skipped")
        with tempfile.TemporaryDirectory(prefix="drive-search-office-") as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / f"source{extension}"
            output_dir = temp_path / "output"
            profile_dir = temp_path / "profile"
            output_dir.mkdir()
            profile_dir.mkdir()
            source_path.write_bytes(content)
            try:
                subprocess.run(  # nosec B603
                    [
                        self.command,
                        "--headless",
                        "--nologo",
                        "--nodefault",
                        "--nolockcheck",
                        "--norestore",
                        f"-env:UserInstallation={profile_dir.as_uri()}",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(output_dir),
                        str(source_path),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise TextExtractionError("office_conversion_timeout") from exc
            except subprocess.CalledProcessError as exc:
                raise TextExtractionError("office_conversion_failed") from exc
            except OSError as exc:
                raise TextExtractionError("office_tool_unavailable", status="skipped") from exc
            output_paths = sorted(output_dir.glob("*.pdf"))
            if len(output_paths) != 1:
                raise TextExtractionError("office_conversion_failed")
            output = output_paths[0].read_bytes()
            if len(output) > self.max_pdf_bytes:
                raise TextExtractionError("office_pdf_too_large", status="skipped")
            return output


def _safe_extension(
    name: str,
    *,
    allowed: set[str],
    fallback: str | None,
) -> str | None:
    normalized_name = name.casefold()
    for extension in sorted(allowed, key=len, reverse=True):
        if normalized_name.endswith(extension):
            return extension
    return fallback


def _rendered_page_number(path: Path) -> int:
    try:
        return int(path.stem.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0
