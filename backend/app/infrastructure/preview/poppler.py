from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from app.modules.preview.converters import (
    PreviewRenderError,
    PreviewRenderTimeoutError,
    PreviewToolUnavailableError,
)


class PopplerPdfPreviewConverter:
    def __init__(
        self,
        *,
        command: str = "pdftoppm",
        dpi: int = 144,
        timeout_seconds: int = 30,
        max_rendered_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.command = command
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds
        self.max_rendered_bytes = max_rendered_bytes

    async def render_first_page_png(self, source: bytes) -> bytes:
        executable = _resolve_executable(self.command)
        if executable is None:
            raise PreviewToolUnavailableError(f"{self.command} not found")

        with TemporaryDirectory(prefix="drive-preview-pdf-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "source.pdf"
            output_prefix = temp_path / "page"
            input_path.write_bytes(source)

            process = await asyncio.create_subprocess_exec(
                executable,
                "-png",
                "-f",
                "1",
                "-singlefile",
                "-r",
                str(self.dpi),
                str(input_path),
                str(output_prefix),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise PreviewRenderTimeoutError("pdf_render_timeout") from exc

            if process.returncode != 0:
                message = stderr.decode("utf-8", "replace").strip() or "pdftoppm failed"
                raise PreviewRenderError(message[:500])

            output_path = output_prefix.with_suffix(".png")
            if not output_path.exists():
                raise PreviewRenderError("pdf_preview_output_missing")
            if output_path.stat().st_size > self.max_rendered_bytes:
                raise PreviewRenderError("pdf_preview_output_too_large")
            return output_path.read_bytes()


def _resolve_executable(command: str) -> str | None:
    executable = shutil.which(command)
    if executable is None:
        return None
    if not _is_windows():
        return executable

    executable_path = Path(executable)
    if executable_path.suffix.casefold() not in {".cmd", ".bat"}:
        return executable

    for candidate in _windows_poppler_exe_candidates(executable_path):
        if candidate.exists():
            return str(candidate)
    return executable


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_poppler_exe_candidates(wrapper_path: Path) -> list[Path]:
    exe_name = wrapper_path.with_suffix(".exe").name
    return [
        wrapper_path.with_suffix(".exe"),
        wrapper_path.parent.parent / "Library" / "bin" / exe_name,
        wrapper_path.parent.parent / "native" / "poppler" / "Library" / "bin" / exe_name,
    ]
