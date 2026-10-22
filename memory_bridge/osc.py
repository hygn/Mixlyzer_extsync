"""The OSC messages Mixlyzer's External Sync takes (its core/external_sync.py):

    /mixlyzer/deck/time     i deck  s path  T|F loaded  T|F active  d seconds
    /mixlyzer/deck/samples  i deck  s path  T|F loaded  T|F active  h samples  i rate (0: the file's own)
"""

from __future__ import annotations

import struct

TIME_ADDRESS = "/mixlyzer/deck/time"
SAMPLES_ADDRESS = "/mixlyzer/deck/samples"


def _padded(raw: bytes) -> bytes:
    return raw + b"\x00" * (4 - len(raw) % 4)


def message(address: str, *args) -> bytes:
    """An OSC 1.0 message: bool as T / F, int as i (h when tagged ("h", n) or past 32 bits), float as d, str as s."""
    tags, body = ",", b""
    for arg in args:
        if isinstance(arg, tuple) and len(arg) == 2 and arg[0] == "h":
            tags += "h"
            body += struct.pack(">q", int(arg[1]))
        elif isinstance(arg, bool):
            tags += "T" if arg else "F"
        elif isinstance(arg, int):
            small = -(1 << 31) <= arg < (1 << 31)
            tags += "i" if small else "h"
            body += struct.pack(">i" if small else ">q", arg)
        elif isinstance(arg, float):
            tags += "d"
            body += struct.pack(">d", arg)
        elif isinstance(arg, str):
            tags += "s"
            body += _padded(arg.encode("utf-8"))
        else:
            raise TypeError(f"not an OSC argument: {type(arg).__name__}")
    return _padded(address.encode("utf-8")) + _padded(tags.encode("ascii")) + body


def deck_message(number: int, path: str, loaded: bool, active: bool, *, seconds=None, samples=None,
                 rate: int = 0) -> bytes:
    if seconds is not None:
        return message(TIME_ADDRESS, int(number), path, bool(loaded), bool(active), float(seconds))
    return message(SAMPLES_ADDRESS, int(number), path, bool(loaded), bool(active), ("h", int(samples or 0)),
                   int(rate))
