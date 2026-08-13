from __future__ import annotations

import os
import sys
from pathlib import Path

from config import RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB


def ensure_resolve_env() -> None:
    os.environ.setdefault("RESOLVE_SCRIPT_API", str(RESOLVE_SCRIPT_API))
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", str(RESOLVE_SCRIPT_LIB))
    modules = str(RESOLVE_SCRIPT_API / "Modules")
    if modules not in sys.path:
        sys.path.insert(0, modules)


def get_resolve():
    """Connect to a running DaVinci Resolve instance."""
    ensure_resolve_env()
    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        raise RuntimeError(
            "Не найден DaVinciResolveScript. Проверь установку Resolve и пути scripting."
        ) from exc

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Resolve не отвечает на scripting. "
            "1) Запусти DaVinci Resolve. "
            "2) Preferences > System > General > External scripting using = Local. "
            "3) Для стабильного API лучше Studio (в Free иногда режется export)."
        )
    return resolve
