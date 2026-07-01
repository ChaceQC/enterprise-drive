from __future__ import annotations

import pytest

from app.infrastructure.preview import libreoffice as libreoffice_module
from app.infrastructure.preview.libreoffice import LibreOfficePreviewConverter
from app.modules.preview.converters import PreviewRenderError, PreviewToolUnavailableError


@pytest.mark.asyncio
async def test_libreoffice_converter_reports_missing_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(libreoffice_module.shutil, "which", lambda command: None)
    converter = LibreOfficePreviewConverter(command="missing-soffice")

    with pytest.raises(PreviewToolUnavailableError) as exc_info:
        await converter.convert_to_pdf(b"office", file_extension=".docx")

    assert exc_info.value.reason == "office_renderer_missing"


def test_normalize_extension_accepts_plain_extension() -> None:
    assert libreoffice_module._normalize_extension("DOCX") == ".docx"


def test_normalize_extension_rejects_shell_like_input() -> None:
    with pytest.raises(PreviewRenderError) as exc_info:
        libreoffice_module._normalize_extension(".docx;rm")

    assert "office_extension_invalid" in str(exc_info.value)
