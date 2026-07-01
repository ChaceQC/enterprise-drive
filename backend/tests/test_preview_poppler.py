from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.preview import poppler as poppler_module


def test_windows_poppler_exe_candidates_include_codex_runtime_layout() -> None:
    wrapper = (
        Path("C:/runtime/dependencies/bin/pdftoppm.cmd")
        if Path("C:/").is_absolute()
        else Path("/runtime/dependencies/bin/pdftoppm.cmd")
    )

    candidates = poppler_module._windows_poppler_exe_candidates(wrapper)

    assert (
        wrapper.parent.parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
        in candidates
    )


def test_resolve_executable_prefers_windows_poppler_exe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "dependencies" / "bin" / "pdftoppm.cmd"
    executable = (
        tmp_path / "dependencies" / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
    )
    wrapper.parent.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    wrapper.write_text("@echo off\n", encoding="utf-8")
    executable.write_bytes(b"")
    monkeypatch.setattr(poppler_module.shutil, "which", lambda command: str(wrapper))
    monkeypatch.setattr(poppler_module.os, "name", "nt")

    assert poppler_module._resolve_executable("pdftoppm") == str(executable)
