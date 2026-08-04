from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
DEFAULT_OUTPUT = FRONTEND_ROOT / "openapi" / "openapi.json"


def _backend_version() -> str:
    pyproject_path = BACKEND_ROOT / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def _render_openapi() -> str:
    sys.path.insert(0, str(BACKEND_ROOT))

    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_name="企业网盘",
        app_version=_backend_version(),
        environment="test",
        api_v1_prefix="/api/v1",
        debug=False,
        tracing_enabled=False,
    )
    schema = create_app(settings).openapi()
    return json.dumps(
        schema,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically export the backend OpenAPI schema.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="OpenAPI JSON output path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the committed OpenAPI archive is current.",
    )
    args = parser.parse_args()

    output_path = args.output.resolve()
    rendered = _render_openapi()

    if args.check:
        if not output_path.is_file():
            parser.error(f"OpenAPI archive does not exist: {output_path}")
        if output_path.read_text(encoding="utf-8") != rendered:
            parser.error(
                "OpenAPI archive is stale. Run `npm run api:generate` in frontend/.",
            )
        print(f"OpenAPI archive is current: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Exported OpenAPI schema to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
