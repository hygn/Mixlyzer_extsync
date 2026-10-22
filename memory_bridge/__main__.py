"""Reads a DJ program's deck state from its memory and sends it to Mixlyzer's External Sync as OSC.

    python -m memory_bridge                       run (bridge.json)
    python -m memory_bridge --once                read each deck once and print it (checking the offsets)
    python -m memory_bridge --processes           the running processes (denied ones marked)
    python -m memory_bridge --import-mixlyzer PATH
                                                  bridge.json from a Mixlyzer config.json of before OSC
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

from memory_bridge import config as bridge_config
from memory_bridge import processes
from memory_bridge.memory import Denied, ProcessReader, find_pid
from memory_bridge.osc import deck_message

RETRY_SEC = 1.0


def _log(message: str) -> None:
    print(f"[bridge] {message}", flush=True)


def _readings(reader: ProcessReader, cfg: bridge_config.BridgeConfig):
    return [reader.deck(deck, cfg) for deck in cfg.decks]


def _packets(readings, cfg: bridge_config.BridgeConfig) -> list[bytes]:
    return [deck_message(r.number, r.path, r.loaded, r.active, seconds=r.seconds, samples=r.samples,
                         rate=cfg.sample_rate) for r in readings]


def run(cfg: bridge_config.BridgeConfig, *, once: bool = False) -> int:
    sock = socket.socket(socket.getaddrinfo(cfg.host, cfg.port, type=socket.SOCK_DGRAM)[0][0], socket.SOCK_DGRAM)
    target = (cfg.host, cfg.port)
    period = 1.0 / cfg.rate_hz
    reader: ProcessReader | None = None
    waiting_logged = ""
    try:
        while True:
            if reader is None:
                try:
                    pid, name = find_pid(cfg)
                    if pid:
                        reader = ProcessReader(pid, name)
                        _log(f"reading {name} (pid {pid}), sending to {cfg.host}:{cfg.port}")
                        waiting_logged = ""
                except Denied as exc:
                    _log(f"refused: {exc}")
                    return 2
                except Exception as exc:
                    if waiting_logged != str(exc):
                        waiting_logged = str(exc)
                        _log(f"could not open the process: {exc}")
                if reader is None:
                    if not waiting_logged:
                        waiting_logged = "not running"
                        _log(f"waiting for {cfg.process_name or cfg.process_pid}")
                    if once:
                        return 1
                    time.sleep(RETRY_SEC)
                    continue
            started = time.perf_counter()
            try:
                readings = _readings(reader, cfg)
            except Exception as exc:   # the process gone, or an address no longer valid
                _log(f"read failed ({exc}); trying again")
                reader.close()
                reader = None
                if once:
                    return 1
                time.sleep(RETRY_SEC)
                continue
            if once:
                for r in readings:
                    print(r)
                return 0
            for packet in _packets(readings, cfg):
                try:
                    sock.sendto(packet, target)
                except OSError as exc:   # nobody listening yet (a refusal is reported on the next send)
                    if waiting_logged != "send":
                        waiting_logged = "send"
                        _log(f"send failed: {exc}")
            time.sleep(max(0.0, period - (time.perf_counter() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        if reader is not None:
            reader.close()
        sock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memory_bridge", description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=bridge_config.DEFAULT_PATH)
    parser.add_argument("--once", action="store_true", help="read each deck once and print it")
    parser.add_argument("--processes", action="store_true", help="list the running processes")
    parser.add_argument("--import-mixlyzer", type=Path, metavar="CONFIG_JSON",
                        help="write --config from a Mixlyzer config.json's memory settings")
    args = parser.parse_args(argv)
    if args.processes:
        for row in sorted(processes.list_processes(), key=lambda r: (str(r["name"]).lower(), int(r["pid"]))):
            mark = "  [denied]" if processes.denied(str(row["name"])) else ""
            print(f"{row['pid']:>8}  {row['name']}{mark}")
        return 0
    if args.import_mixlyzer:
        if args.config.exists():
            print(f"{args.config} exists: not overwritten", file=sys.stderr)
            return 1
        bridge_config.save(bridge_config.from_mixlyzer(args.import_mixlyzer), args.config)
        print(f"written: {args.config}")
        return 0
    try:
        cfg = bridge_config.load(args.config)
    except FileNotFoundError:
        print(f"{args.config} not found: copy bridge.example.json there and fill it in", file=sys.stderr)
        return 1
    return run(cfg, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
