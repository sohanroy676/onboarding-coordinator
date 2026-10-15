"""Append-only JSON Lines ledger with a SHA-256 hash chain.

One line per entry: seq, ts, run_id, event, data, prev_hash, hash.
hash covers every field except hash itself. The first entry links to
GENESIS_HASH. Each domain writes only its own ledger file.

The canonical encoding is repeated here on purpose: ledger/ must not
import from coordinator/.

Limit of a hash chain: removing entries from the end of the file is not
detectable from the file alone.
"""

import hashlib
import json
import os
import threading

GENESIS_HASH = "0" * 64

_FIELDS = {"seq", "ts", "run_id", "event", "data", "prev_hash", "hash"}


class LedgerCorrupt(Exception):
    """Raised when a ledger file cannot be read as a valid chain."""

    def __init__(self, message, position=None):
        super().__init__(message)
        self.position = position


def _canonical(obj):
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return text.encode("ascii")


def entry_hash(entry):
    """Hash of an entry over all fields except hash."""
    body = {key: value for key, value in entry.items() if key != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def read_entries(path):
    """Read every entry of a ledger file; raise LedgerCorrupt on bad lines.

    A missing file is an empty ledger.
    """
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="ascii", newline="\n") as handle:
        for position, line in enumerate(handle):
            if not line.endswith("\n"):
                raise LedgerCorrupt("entry %d is truncated" % position, position)
            try:
                entries.append(json.loads(line))
            except ValueError as exc:
                raise LedgerCorrupt(
                    "entry %d is not valid JSON" % position, position
                ) from exc
    return entries


def verify_entries(entries):
    """Check seq numbers and hash links.

    Returns (True, None) for an intact chain, or (False, position) for
    the first entry at which the chain breaks.
    """
    previous = GENESIS_HASH
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != _FIELDS:
            return False, position
        if entry["seq"] != position:
            return False, position
        if entry["prev_hash"] != previous:
            return False, position
        try:
            expected = entry_hash(entry)
        except (TypeError, ValueError):
            return False, position
        if entry["hash"] != expected:
            return False, position
        previous = entry["hash"]
    return True, None


def verify_file(path):
    """Verify a ledger file; an unreadable entry counts as a break."""
    try:
        entries = read_entries(path)
    except LedgerCorrupt as exc:
        return False, exc.position
    return verify_entries(entries)


class Ledger:
    """Writer for one append-only ledger file."""

    def __init__(self, path, clock):
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        entries = read_entries(path)
        ok, position = verify_entries(entries)
        if not ok:
            raise LedgerCorrupt("chain broken at entry %s" % position, position)
        self._next_seq = len(entries)
        self._last_hash = entries[-1]["hash"] if entries else GENESIS_HASH

    def append(self, run_id, event, data):
        """Append one entry and return it. Raises on any write failure."""
        with self._lock:
            entry = {
                "seq": self._next_seq,
                "ts": self._clock(),
                "run_id": run_id,
                "event": event,
                "data": data,
                "prev_hash": self._last_hash,
            }
            entry["hash"] = entry_hash(entry)
            line = _canonical(entry).decode("ascii") + "\n"
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="ascii", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            self._next_seq += 1
            self._last_hash = entry["hash"]
            return entry

    def entries(self):
        return read_entries(self._path)

    def verify(self):
        return verify_file(self._path)
