from __future__ import annotations

import importlib
import os
from typing import Any

# Locust performs gevent monkey-patching during import. Pytest plugins may have
# imported ssl/urllib3 first on the Linux runner, which makes that late patch
# recurse on Python 3.12. These tests exercise report/runner helpers rather than
# gevent scheduling, so load Locust's test API without patching and restore the
# caller's environment before subprocess-based runner checks.
_skip_monkey_patch = os.environ.get("LOCUST_SKIP_MONKEY_PATCH")
os.environ["LOCUST_SKIP_MONKEY_PATCH"] = "1"
try:
    EventHook: type[Any] = importlib.import_module("locust.event").EventHook
finally:
    if _skip_monkey_patch is None:
        os.environ.pop("LOCUST_SKIP_MONKEY_PATCH", None)
    else:
        os.environ["LOCUST_SKIP_MONKEY_PATCH"] = _skip_monkey_patch
