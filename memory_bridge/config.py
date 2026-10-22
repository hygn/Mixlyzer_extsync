"""The bridge's settings (bridge.json): where Mixlyzer listens, the process read, and where each deck's state is
in its memory (pointer chains). bridge.json holds the user's own addresses and is not committed;
bridge.example.json shows its shape."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "bridge.json"
VALUE_TYPES = ("float", "bool", "str", "int")


@dataclass
class ValueSpec:
    """A value in the process's memory. ``offsets``: a comma-separated hex pointer chain, the first an offset
    from the process's main module (prefix "g" for an absolute address), each following one dereferenced and
    added; ``type``: float, bool, str or int; a string's ``length`` (bytes read, cut at the first NUL) and
    ``encoding``; a flag's ``bit_pos`` (0 - 7; above: the whole byte); a time's ``multiplier`` to seconds."""
    offsets: str = "0"
    type: str = "float"
    length: int = 0
    encoding: str = "utf-8"
    bit_pos: int = 0
    multiplier: float = 1.0


@dataclass
class DeckSpec:
    number: int = 1
    time: ValueSpec = field(default_factory=lambda: ValueSpec(type="float"))
    sample_index: ValueSpec = field(default_factory=lambda: ValueSpec(type="int"))
    path: ValueSpec = field(default_factory=lambda: ValueSpec(type="str", length=2048))
    active: ValueSpec = field(default_factory=lambda: ValueSpec(type="bool"))
    loaded: ValueSpec = field(default_factory=lambda: ValueSpec(type="bool"))


@dataclass
class BridgeConfig:
    host: str = "127.0.0.1"              # Mixlyzer's External Sync address and port
    port: int = 39321
    rate_hz: float = 60.0                # readings sent a second
    process_name: str = ""               # the process read (by name, or by pid when not 0)
    process_pid: int = 0
    position: str = "sample_index"       # "time" (seconds, after its multiplier) or "sample_index"
    sample_rate: int = 44100             # the rate the samples are counted at; 0: the file's own
    decks: list[DeckSpec] = field(default_factory=lambda: [DeckSpec(1), DeckSpec(2)])


def _value(raw) -> ValueSpec:
    raw = raw if isinstance(raw, dict) else {}
    spec = ValueSpec(
        offsets=str(raw.get("offsets", "0")),
        type=str(raw.get("type", raw.get("value_type", "float"))),
        length=int(raw.get("length", 0) or 0),
        encoding=str(raw.get("encoding", "utf-8") or "utf-8"),
        bit_pos=int(raw.get("bit_pos", 0) or 0),
        multiplier=float(raw.get("multiplier", 1.0)),
    )
    if spec.type not in VALUE_TYPES:
        raise ValueError(f"value type {spec.type!r}: not one of {', '.join(VALUE_TYPES)}")
    return spec


def _deck(raw, number: int) -> DeckSpec:
    raw = raw if isinstance(raw, dict) else {}
    return DeckSpec(int(raw.get("number", number)), *(_value(raw.get(k)) for k in
                                                       ("time", "sample_index", "path", "active", "loaded")))


def from_dict(raw: dict) -> BridgeConfig:
    cfg = BridgeConfig(
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 39321)),
        rate_hz=float(raw.get("rate_hz", 60.0)),
        process_name=str(raw.get("process_name", "")),
        process_pid=int(raw.get("process_pid", 0) or 0),
        position=str(raw.get("position", "sample_index")),
        sample_rate=int(raw.get("sample_rate", 44100)),
        decks=[_deck(d, i + 1) for i, d in enumerate(raw.get("decks") or [])],
    )
    if cfg.position not in ("time", "sample_index"):
        raise ValueError(f"position {cfg.position!r}: time or sample_index")
    if not 0 < cfg.rate_hz <= 1000 or not 0 < cfg.port < 65536 or cfg.sample_rate < 0:
        raise ValueError("rate_hz, port or sample_rate out of range")
    return cfg


def load(path: Path = DEFAULT_PATH) -> BridgeConfig:
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save(cfg: BridgeConfig, path: Path = DEFAULT_PATH) -> None:
    Path(path).write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def from_mixlyzer(path: Path) -> BridgeConfig:
    """The memory settings of a Mixlyzer config.json from before External Sync took OSC (its
    externalsyncconfig: memory_process_*, memory_deck1 / 2, mode, total_sample_count_source)."""
    sync = json.loads(Path(path).read_text(encoding="utf-8")).get("externalsyncconfig") or {}
    if "memory_deck1" not in sync:
        raise ValueError(f"{path}: no memory settings (External Sync already on OSC?)")
    by_file = sync.get("total_sample_count_source") == "file"
    return from_dict({
        "process_name": sync.get("memory_process_name", ""),
        "process_pid": sync.get("memory_process_pid", 0),
        "position": "time" if sync.get("mode") == "time" else "sample_index",
        "sample_rate": 0 if by_file else int(sync.get("reference_sample_rate", 44100) or 44100),
        "decks": [{"number": n, **sync.get(f"memory_deck{n}", {})} for n in (1, 2)],
    })
