from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from app.modules.preview.converters import (
    PreviewRenderError,
    PreviewRenderTimeoutError,
    PreviewToolUnavailableError,
    PreviewUnsupportedError,
)


class LibreOfficePreviewConverter:
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

    async def convert_to_pdf(self, source: bytes, *, file_extension: str) -> bytes:
        executable = shutil.which(self.command)
        if executable is None:
            raise PreviewToolUnavailableError(
                f"{self.command} not found",
                reason="office_renderer_missing",
            )

        with TemporaryDirectory(prefix="drive-preview-office-") as temp_dir:
            temp_path = Path(temp_dir)
            profile_path = temp_path / "profile"
            profile_path.mkdir()
            safe_extension = _normalize_extension(file_extension)
            input_path = temp_path / f"source{safe_extension}"
            input_path.write_bytes(source)

            process = await asyncio.create_subprocess_exec(
                executable,
                f"-env:UserInstallation={profile_path.as_uri()}",
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_path),
                str(input_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise PreviewRenderTimeoutError(
                    "office_render_timeout",
                    reason="office_render_timeout",
                ) from exc

            if process.returncode != 0:
                message = _decode_output(stdout=stdout, stderr=stderr) or "LibreOffice failed"
                raise PreviewRenderError(message[:500], reason="office_render_failed")

            output_path = input_path.with_suffix(".pdf")
            if not output_path.exists():
                raise PreviewRenderError(
                    "office_preview_output_missing",
                    reason="office_render_failed",
                )
            if output_path.stat().st_size > self.max_pdf_bytes:
                raise PreviewUnsupportedError(
                    "office_preview_output_too_large",
                    reason="office_preview_output_too_large",
                )
            return output_path.read_bytes()


def _normalize_extension(file_extension: str) -> str:
    extension = file_extension.strip().lower()
    if not extension.startswith("."):
        extension = f".{extension}"
    if not extension[1:].replace("_", "").isalnum():
        raise PreviewRenderError("office_extension_invalid", reason="office_render_failed")
    return extension


def _decode_output(*, stdout: bytes, stderr: bytes) -> str:
    output = (stderr or stdout).decode("utf-8", "replace").strip()
    return output
