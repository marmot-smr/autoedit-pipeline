from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolve_api import get_resolve


def main() -> int:
    try:
        resolve = get_resolve()
    except Exception as e:
        # Windows cp1251 console can choke on some unicode; keep it plain
        msg = str(e).encode("cp1251", errors="replace").decode("cp1251")
        print("FAIL:", msg)
        return 1

    name = resolve.GetProductName()
    ver = resolve.GetVersionString()
    print(f"OK: connected to {name} {ver}")
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    print("Current project:", proj.GetName() if proj else "(none)")
    print("External scripting works. You can process inbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
