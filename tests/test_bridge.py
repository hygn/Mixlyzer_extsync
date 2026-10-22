import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_bridge import config, memory, osc, processes  # noqa: E402


class OscTests(unittest.TestCase):
    def test_deck_messages(self):
        packet = osc.deck_message(2, "/m/a.flac", True, False, samples=441000, rate=44100)
        self.assertTrue(packet.startswith(b"/mixlyzer/deck/samples\x00\x00,isTFhi\x00"))
        self.assertEqual(struct.unpack(">qi", packet[-12:]), (441000, 44100))
        self.assertEqual(len(packet) % 4, 0)
        packet = osc.deck_message(1, "", False, True, seconds=1.5)
        self.assertTrue(packet.startswith(b"/mixlyzer/deck/time\x00,isFTd\x00\x00"))
        self.assertEqual(struct.unpack(">d", packet[-8:])[0], 1.5)


class ConfigTests(unittest.TestCase):
    def test_example_round_trip(self):
        root = Path(__file__).resolve().parents[1]
        cfg = config.load(root / "bridge.example.json")
        self.assertEqual([d.number for d in cfg.decks], [1, 2])
        offsets = {v["offsets"] for d in json.loads((root / "bridge.example.json").read_text())["decks"]
                   for v in d.values() if isinstance(v, dict)}
        self.assertEqual(offsets, {"0"})   # the example holds no address

    def test_from_mixlyzer(self):
        value = {"offsets": "1000,10", "value_type": "int", "length": 0, "encoding": "utf-8", "bit_pos": 0,
                 "multiplier": 1.0}
        deck = {k: dict(value) for k in ("time", "sample_index", "path", "active", "loaded")}
        sync = {"enabled": True, "mode": "sample_index", "total_sample_count_source": "file",
                "reference_sample_rate": 48000, "memory_process_name": "dj.exe", "memory_process_pid": 0,
                "memory_deck1": deck, "memory_deck2": deck}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"externalsyncconfig": sync}))
            cfg = config.from_mixlyzer(path)
            path.write_text(json.dumps({"externalsyncconfig": {"enabled": False, "osc_port": 1}}))
            with self.assertRaises(ValueError):
                config.from_mixlyzer(path)
        self.assertEqual((cfg.process_name, cfg.position, cfg.sample_rate), ("dj.exe", "sample_index", 0))
        self.assertEqual(cfg.decks[1].sample_index.offsets, "1000,10")

    def test_bad_values_refused(self):
        for raw in ({"position": "beats"}, {"port": 0}, {"rate_hz": 0},
                    {"decks": [{"time": {"type": "double"}}]}):
            with self.subTest(raw), self.assertRaises(ValueError):
                config.from_dict(raw)


class MemoryTests(unittest.TestCase):
    def test_offsets(self):
        self.assertEqual(memory.parse_offsets("1000, 10,0x20"), (False, [0x1000, 0x10, 0x20]))
        self.assertEqual(memory.parse_offsets("g1000,10"), (True, [0x1000, 0x10]))
        with self.assertRaises(ValueError):
            memory.parse_offsets("12,zz")

    def test_denied_process_never_opened(self):
        cfg = config.BridgeConfig(process_name="lsass.exe")
        with mock.patch.object(processes, "list_processes", return_value=[{"name": "lsass.exe", "pid": 7}]):
            with self.assertRaises(memory.Denied):
                memory.find_pid(cfg)
        with mock.patch.object(processes, "list_processes", return_value=[]):
            self.assertEqual(memory.find_pid(cfg), (0, ""))

    def test_denylist_fails_closed(self):
        processes._denylist.cache_clear()
        try:
            with mock.patch.object(processes, "DENYLIST", Path("missing.json")):
                processes._denylist.cache_clear()
                self.assertTrue(processes.denied("anything"))
        finally:
            processes._denylist.cache_clear()
        self.assertTrue(processes.denied("x", r"C:\Program Files\BattlEye\x.exe"))
        self.assertFalse(processes.denied("player"))


class ProcessTests(unittest.TestCase):
    def test_processes_listed(self):
        rows = processes.list_processes()
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(r["pid"], int) and r["name"] for r in rows))

    def test_ps_output_parsed(self):
        out = " 1 /sbin/launchd\n 42 /opt/dj app/bin/djapp\nbad\n"
        with mock.patch.object(processes, "IS_WINDOWS", False), \
                mock.patch.object(subprocess, "check_output", return_value=out):
            rows = processes.list_processes()
        self.assertEqual(rows, [{"name": "launchd", "pid": 1}, {"name": "djapp", "pid": 42}])


if __name__ == "__main__":
    unittest.main()
