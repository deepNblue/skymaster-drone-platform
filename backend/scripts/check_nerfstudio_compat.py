"""Probe nerfstudio 1.1.5 dependency constraints from PyPI (no install)."""
from __future__ import annotations

import json
import urllib.request

with urllib.request.urlopen("https://pypi.org/pypi/nerfstudio/1.1.5/json", timeout=20) as f:
    info = json.load(f)["info"]

print("requires_python:", info.get("requires_python"))
for req in info.get("requires_dist", []) or []:
    low = req.lower()
    if any(k in low for k in ("torch", "gsplat", "nerfstudio", "cuda", "python")):
        print("  ", req)
