"""The running processes, and the ones the bridge never opens (process_denylist.json: system, security,
anti-cheat, password and remote-desktop software). The denylist fails closed: when it cannot be read, every
process is denied."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from memory_bridge.config import ROOT

IS_WINDOWS = sys.platform == "win32"
DENYLIST = ROOT / "process_denylist.json"


def _windows_program(*parts: str) -> str:
    """By its full path: a bare name is looked for in the current folder first."""
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", *parts)


def _hidden() -> dict:
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WINDOWS else {}


def list_processes() -> list[dict[str, int | str]]:
    """The running processes as {"name", "pid"} (tasklist on Windows, ps elsewhere); [] when it cannot be read."""
    command = ([_windows_program("System32", "tasklist.exe"), "/FO", "CSV", "/NH"] if IS_WINDOWS
               else ["ps", "-A", "-o", "pid=,comm="])
    try:
        out = subprocess.check_output(command, text=True, encoding="utf-8", errors="replace", **_hidden())
    except Exception:
        return []
    rows: list[dict[str, int | str]] = []
    if IS_WINDOWS:
        for row in csv.reader(io.StringIO(out)):
            if len(row) < 2:
                continue
            try:
                pid = int(str(row[1]).strip())
            except ValueError:
                continue
            name = str(row[0]).strip()
            if name:
                rows.append({"name": name, "pid": pid})
        return rows
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        # ps gives the command's path on some systems: its file name is the process name
        name = os.path.basename(parts[1].strip())
        if name:
            rows.append({"name": name, "pid": pid})
    return rows


def normalize_name(name: str) -> str:
    text = str(name or "").strip().lower()
    return text[:-4] if text.endswith(".exe") else text


def normalize_image_path(path: str) -> str:
    return str(path or "").strip().lower().replace("/", "\\")


@lru_cache(maxsize=1)
def _denylist() -> tuple[frozenset[str], tuple[str, ...]] | None:
    try:
        payload = json.loads(DENYLIST.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    names = frozenset(n for n in (normalize_name(x) for x in payload.get("blocked_process_names", [])) if n)
    paths = tuple(p for p in (normalize_image_path(x) for x in payload.get("blocked_path_keywords", [])) if p)
    return names, paths


def denied(name: str, image_path: str = "") -> bool:
    """Whether the process is never opened (every process, when the denylist cannot be read)."""
    deny = _denylist()
    if deny is None:
        return True
    names, paths = deny
    if normalize_name(name) in names:
        return True
    image = normalize_image_path(image_path)
    return bool(image) and any(keyword in image for keyword in paths)
