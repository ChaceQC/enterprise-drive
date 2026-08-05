from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

UploadCompletePhase = Literal[
    "pre_storage",
    "storage_complete",
    "hash_validation",
    "final_object",
    "db_finalize",
    "temp_delete",
]


@dataclass
class UploadCompleteTimings:
    pre_storage_ms: float = 0.0
    storage_complete_ms: float = 0.0
    hash_validation_ms: float = 0.0
    final_object_ms: float = 0.0
    db_finalize_ms: float = 0.0
    temp_delete_ms: float = 0.0

    @contextmanager
    def measure(self, phase: UploadCompletePhase) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter() - started) * 1000
            attribute = f"{phase}_ms"
            setattr(self, attribute, float(getattr(self, attribute)) + elapsed_ms)

    def server_timing_header(self) -> str:
        return ", ".join(
            (
                f"pre_storage;dur={self.pre_storage_ms:.3f}",
                f"storage_complete;dur={self.storage_complete_ms:.3f}",
                f"hash_validation;dur={self.hash_validation_ms:.3f}",
                f"final_object;dur={self.final_object_ms:.3f}",
                f"db_finalize;dur={self.db_finalize_ms:.3f}",
                f"temp_delete;dur={self.temp_delete_ms:.3f}",
            )
        )


def measure_upload_complete_phase(
    timings: UploadCompleteTimings | None,
    phase: UploadCompletePhase,
) -> AbstractContextManager[None]:
    if timings is None:
        return nullcontext()
    return timings.measure(phase)


def start_upload_complete_phase(timings: UploadCompleteTimings | None) -> float | None:
    return perf_counter() if timings is not None else None


def record_upload_complete_phase_elapsed(
    timings: UploadCompleteTimings | None,
    phase: UploadCompletePhase,
    started_at: float | None,
) -> None:
    if timings is None or started_at is None:
        return
    elapsed_ms = (perf_counter() - started_at) * 1000
    attribute = f"{phase}_ms"
    setattr(timings, attribute, float(getattr(timings, attribute)) + elapsed_ms)
