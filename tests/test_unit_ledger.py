import json
import pathlib
import tempfile
import unittest

from ledger.ledger import (
    GENESIS_HASH,
    Ledger,
    LedgerCorrupt,
    entry_hash,
    read_entries,
    verify_entries,
    verify_file,
)
from tests.helpers import FakeClock


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "hr" / "ledger.jsonl"
        self.clock = FakeClock()

    def _filled(self, count=4):
        ledger = Ledger(self.path, self.clock)
        for index in range(count):
            self.clock.advance(1)
            ledger.append("run1", "action", {"n": index})
        return ledger

    def _lines(self):
        return self.path.read_text(encoding="ascii").splitlines()

    def _write(self, lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="ascii")

    def test_first_entry_links_to_genesis(self):
        ledger = Ledger(self.path, self.clock)
        entry = ledger.append("run1", "start", {})
        self.assertEqual(entry["seq"], 0)
        self.assertEqual(entry["prev_hash"], GENESIS_HASH)
        self.assertEqual(ledger.verify(), (True, None))

    def test_chain_links_and_verifies(self):
        ledger = self._filled(4)
        entries = ledger.entries()
        self.assertEqual([e["seq"] for e in entries], [0, 1, 2, 3])
        for earlier, later in zip(entries, entries[1:]):
            self.assertEqual(later["prev_hash"], earlier["hash"])
        self.assertEqual(ledger.verify(), (True, None))

    def test_reopen_continues_chain(self):
        self._filled(2)
        again = Ledger(self.path, self.clock)
        entry = again.append("run2", "action", {})
        self.assertEqual(entry["seq"], 2)
        self.assertEqual(again.verify(), (True, None))

    def test_missing_file_is_empty_and_valid(self):
        self.assertEqual(read_entries(self.path), [])
        self.assertEqual(verify_file(self.path), (True, None))
        self.assertEqual(verify_entries([]), (True, None))

    def test_tampered_data_detected_at_that_entry(self):
        self._filled(4)
        lines = self._lines()
        entry = json.loads(lines[2])
        entry["data"] = {"n": 99}
        lines[2] = json.dumps(entry)
        self._write(lines)
        self.assertEqual(verify_file(self.path), (False, 2))

    def test_deleted_middle_line_detected(self):
        self._filled(4)
        lines = self._lines()
        del lines[1]
        self._write(lines)
        self.assertEqual(verify_file(self.path), (False, 1))

    def test_reordered_lines_detected(self):
        self._filled(4)
        lines = self._lines()
        lines[1], lines[2] = lines[2], lines[1]
        self._write(lines)
        self.assertFalse(verify_file(self.path)[0])

    def test_recomputed_hash_after_edit_still_breaks_next_link(self):
        self._filled(3)
        lines = self._lines()
        entry = json.loads(lines[0])
        entry["data"] = {"n": 42}
        entry["hash"] = entry_hash(entry)
        lines[0] = json.dumps(entry)
        self._write(lines)
        self.assertEqual(verify_file(self.path), (False, 1))

    def test_truncated_last_line_is_reported_not_ignored(self):
        self._filled(3)
        text = self.path.read_text(encoding="ascii")
        self.path.write_text(text[:-20], encoding="ascii")
        self.assertEqual(verify_file(self.path), (False, 2))
        with self.assertRaises(LedgerCorrupt):
            Ledger(self.path, self.clock)

    def test_garbage_line_reported(self):
        self._filled(2)
        lines = self._lines()
        lines.append("not json")
        self._write(lines)
        self.assertEqual(verify_file(self.path), (False, 2))

    def test_extra_or_missing_field_detected(self):
        self._filled(2)
        lines = self._lines()
        entry = json.loads(lines[1])
        entry["extra"] = 1
        lines[1] = json.dumps(entry)
        self._write(lines)
        self.assertEqual(verify_file(self.path), (False, 1))

    def test_non_dict_entry_detected(self):
        self.assertEqual(verify_entries([[1, 2]]), (False, 0))

    def test_unserialisable_data_raises_and_writes_nothing(self):
        ledger = Ledger(self.path, self.clock)
        with self.assertRaises(TypeError):
            ledger.append("run1", "bad", {"x": {1, 2}})
        with self.assertRaises(ValueError):
            ledger.append("run1", "bad", {"x": float("nan")})
        self.assertFalse(self.path.exists())
        entry = ledger.append("run1", "ok", {})
        self.assertEqual(entry["seq"], 0)

    def test_lines_are_ascii_and_canonical(self):
        ledger = Ledger(self.path, self.clock)
        ledger.append("run1", "name", {"who": "Zo\u00eb"})
        raw = self.path.read_bytes()
        raw.decode("ascii")
        self.assertEqual(ledger.verify(), (True, None))


if __name__ == "__main__":
    unittest.main()
