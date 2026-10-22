# Mixlyzer External Sync bridge

Reads a DJ program's deck state (the track loaded, its position, whether the deck is loaded and active) from
that program's memory and sends it to [Mixlyzer](https://github.com/hygn/Mixlyzer)'s External Sync as OSC.
Mixlyzer then follows the deck: it loads the same track and keeps its playhead with it.

Mixlyzer itself reads no other program's memory; any program sending its OSC messages can drive it. This bridge
is one such sender, kept apart from Mixlyzer.

- The process is opened for reading only (on Windows `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`); nothing is
  ever written to it.
- Processes on `process_denylist.json` (system, security, anti-cheat, password and remote-desktop software) are
  never opened, by name or by executable path. When the list cannot be read, every process is refused.
- Windows and Linux (PyMemoryEditor). On Linux reading another process needs ptrace permission
  (`kernel.yama.ptrace_scope`).
- Opening a game's or a protected program's process can trip its anti-cheat or an antivirus: point the bridge
  only at the program you mean to follow.

## Setup

```
uv sync
copy bridge.example.json bridge.json     (cp on Linux)
```

Fill in `bridge.json`: the process (`process_name`, or `process_pid` when not 0) and, for each deck, where its
values are in memory. **`bridge.json` holds your addresses: it is git-ignored, keep it that way.**

Each value is a pointer chain, `offsets`: comma-separated hex, the first an offset from the process's main
module (prefix `g` for an absolute address), each following one dereferenced and added as an offset; `type`
(`float`, `int`, `bool`, `str`); a string's `length` and `encoding`; a flag's `bit_pos` (0 - 7, above: the whole
byte); a time's `multiplier` to seconds.

- `position`: `time` (the deck's `time` value, times its `multiplier`) or `sample_index` (its `sample_index`
  value).
- `sample_rate`: the rate the sample index counts at; 0: the file's own rate.
- `host` / `port`: Mixlyzer's Settings > External Sync (127.0.0.1:39321 by default).

A Mixlyzer `config.json` from before External Sync took OSC still holds the memory settings; they become a
`bridge.json` with

```
uv run python -m memory_bridge --import-mixlyzer path/to/Mixlyzer/config.json
```

## Use

```
uv run python -m memory_bridge --processes     the running processes (denied ones marked)
uv run python -m memory_bridge --once          each deck read once and printed: check the addresses
uv run python -m memory_bridge                 send to Mixlyzer until stopped (Ctrl+C)
```

Turn on Settings > External Sync in Mixlyzer; its status line says which deck it follows.

## The messages

One per deck, `rate_hz` times a second (UDP, OSC 1.0):

```
/mixlyzer/deck/time     i deck  s path  T|F loaded  T|F active  d seconds
/mixlyzer/deck/samples  i deck  s path  T|F loaded  T|F active  h samples  i rate
```

## Licence

LGPL-3.0-or-later, as Mixlyzer.
