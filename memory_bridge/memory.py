"""A process opened for reading (PyMemoryEditor; on Windows PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only:
nothing is ever written) and the deck values read from it through the pointer chains of bridge.json."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from memory_bridge import processes
from memory_bridge.config import BridgeConfig, DeckSpec, ValueSpec

_READ_ONLY = 0x0400 | 0x0010   # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ


class Denied(Exception):
    pass


@dataclass
class DeckReading:
    number: int
    path: str
    loaded: bool
    active: bool
    seconds: Optional[float]   # cfg.position == "time"
    samples: Optional[int]     # cfg.position == "sample_index"


def parse_offsets(text: str) -> tuple[bool, list[int]]:
    """(absolute, the chain's offsets) of "1000,10,20" (relative to the main module) or "g1000,10" (an absolute
    first address)."""
    tokens = [t.strip() for t in str(text).split(",") if t.strip()]
    absolute = bool(tokens) and tokens[0][:1].lower() == "g"
    values = []
    for token in tokens:
        token = token[1:] if token[:1].lower() == "g" else token
        values.append(int(token.lower().replace("0x", ""), 16))
    return absolute, values


class ProcessReader:
    def __init__(self, pid: int, name: str) -> None:
        from PyMemoryEditor import OpenProcess   # imported where memory is read

        kwargs: dict[str, Any] = {"pid": int(pid)}
        if processes.IS_WINDOWS:
            kwargs["permission"] = _READ_ONLY
        self._pm = OpenProcess(**kwargs)
        try:
            modules = list(self._pm.get_modules())
            wanted = processes.normalize_name(name)
            main = next((m for m in modules if processes.normalize_name(m.name) == wanted),
                        modules[0] if modules else None)
            if main is None:
                raise OSError(f"no module in process {pid}")
            if processes.denied(name, str(main.path or "")):
                raise Denied(f"{name} ({main.path}) is on the denylist")
            self.base = int(main.base_address)
        except BaseException:
            self.close()
            raise
        self.pid = int(pid)

    def close(self) -> None:
        try:
            self._pm.close()
        except Exception:
            pass

    def address(self, offsets: str) -> int:
        absolute, chain = parse_offsets(offsets)
        if not chain:
            raise ValueError("empty offset chain")
        base = chain[0] if absolute else self.base + chain[0]
        return base if len(chain) == 1 else int(self._pm.resolve_pointer_chain(base, chain[1:]))

    def value(self, spec: ValueSpec):
        address = self.address(spec.offsets)
        if address <= 0:
            raise ValueError("invalid address")
        if spec.type == "str":
            raw = self._pm.read_bytes(address, max(1, int(spec.length)))
            return raw.decode(spec.encoding or "utf-8", errors="replace").split("\x00", 1)[0]
        if spec.type == "float":
            return float(self._pm.read_float(address))
        if spec.type == "int":
            return int(self._pm.read_int(address))
        byte = self._pm.read_bytes(address, 1)[0]
        return bool((byte >> spec.bit_pos) & 1) if 0 <= spec.bit_pos <= 7 else bool(byte)

    def deck(self, spec: DeckSpec, cfg: BridgeConfig) -> DeckReading:
        loaded, active = bool(self.value(spec.loaded)), bool(self.value(spec.active))
        if not loaded:
            return DeckReading(spec.number, "", False, active, 0.0 if cfg.position == "time" else None,
                               None if cfg.position == "time" else 0)
        path = str(self.value(spec.path) or "").strip()
        if cfg.position == "time":
            seconds = max(0.0, float(self.value(spec.time)) * float(spec.time.multiplier))
            return DeckReading(spec.number, path, True, active, seconds, None)
        return DeckReading(spec.number, path, True, active, None, max(0, int(self.value(spec.sample_index))))


def find_pid(cfg: BridgeConfig) -> tuple[int, str]:
    """(pid, name) of the process to read; (0, "") when it is not running. Denied: a denylisted one."""
    rows = processes.list_processes()
    if cfg.process_pid > 0:
        row = next((r for r in rows if int(r["pid"]) == cfg.process_pid), None)
        if row is None:
            return 0, ""
        name = str(row["name"])
    else:
        wanted = processes.normalize_name(cfg.process_name)
        row = next((r for r in rows if processes.normalize_name(str(r["name"])) == wanted), None) if wanted else None
        if row is None:
            return 0, ""
        name = str(row["name"])
    if processes.denied(name):   # before the process is opened
        raise Denied(f"{name} is on the denylist")
    return int(row["pid"]), name
