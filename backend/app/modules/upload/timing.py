from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

UploadCompletePhase = Literal[
    "storage_complete",
    "hash_validation",
    "final_object",
]


@dataclass
class UploadCompleteTimings:
    storage_complete_ms: float = 0.0
    hash_validation_ms: float = 0.0
    final_object_ms: float = 0.0

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
                f"storage_complete;dur={self.storage_complete_ms:.3f}",
                f"hash_validation;dur={self.hash_validation_ms:.3f}",
                f"final_object;dur={self.final_object_ms:.3f}",
            )
        )


def measure_upload_complete_phase(
    timings: UploadCompleteTimings | None,
    phase: UploadCompletePhase,
) -> AbstractContextManager[None]:
    if timings is None:
        return nullcontext()
    return timings.measure(phase)
