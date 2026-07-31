from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare_prometheus_multiprocess_dir() -> Path | None:
    raw_path = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not raw_path:
        return None

    metrics_dir = Path(raw_path).resolve()
    if metrics_dir == Path(metrics_dir.anchor):
        raise RuntimeError("PROMETHEUS_MULTIPROC_DIR cannot be a filesystem root")
    metrics_dir.mkdir(parents=True, exist_ok=True)
    for metric_file in metrics_dir.glob("*.db"):
        metric_file.unlink()
    return metrics_dir


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("runtime command is required")
    prepare_prometheus_multiprocess_dir()
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
