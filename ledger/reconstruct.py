"""Read-only auditor: rebuild one run from the three domain ledgers.

Run from the project root:

    python -m ledger.reconstruct <run_id> [--state-dir PATH]

The state dir defaults to OC_STATE_DIR, then ./state. Each domain ledger is
read and checked with the hash chain. A domain whose chain is broken is
reported and its lines are not counted.

Action outcomes are counted per (jti, action), and the last line for a pair
wins. A handler fault writes action_executed and then action_failed, so that
action is counted once, as failed. token_rejected lines are counted apart from
action lines. Nothing here writes to a ledger or creates a file.
"""

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ledger.ledger import LedgerCorrupt, read_entries, verify_entries

DOMAINS = ("hr", "it", "facilities")
LEDGER_NAME = "ledger.jsonl"
ACTION_OUTCOMES = {
    "action_executed": "executed",
    "action_refused": "refused",
    "action_failed": "failed",
}
REJECTED_EVENT = "token_rejected"
OUTCOMES = ("executed", "refused", "failed")
LIMITS = (
    "limits: end-of-file truncation is not detectable; the hash chain cannot see removed last lines",
    "limits: a deleted consumed-approval marker re-opens replay; markers are not in any ledger",
    "limits: an aborted run (approval refused) leaves no ledger line",
    "limits: a not_executed action (domain unreachable or bad answer) leaves no ledger line",
    "limits: token_rejected lines can be added by anyone with write access to a ledger file",
)


@dataclass
class DomainEvidence:
    domain: str
    chain_error: str | None = None
    outcomes: Counter = field(default_factory=Counter)
    rejected: int = 0

    @property
    def chain_ok(self):
        return self.chain_error is None


@dataclass
class Rebuild:
    run_id: str
    domains: list

    @property
    def chain_ok(self):
        return all(evidence.chain_ok for evidence in self.domains)


def _read_domain(path):
    """Return (entries, None) for an intact ledger, or (None, reason)."""
    try:
        entries = read_entries(path)
    except LedgerCorrupt as exc:
        return None, str(exc)
    ok, position = verify_entries(entries)
    if not ok:
        return None, "chain broken at entry %d" % position
    return entries, None


def _rebuild_domain(domain, path, run_id):
    evidence = DomainEvidence(domain)
    entries, error = _read_domain(path)
    if error is not None:
        evidence.chain_error = error
        return evidence
    last_outcome = {}
    for entry in entries:
        if entry["run_id"] != run_id:
            continue
        if entry["event"] == REJECTED_EVENT:
            evidence.rejected += 1
        elif entry["event"] in ACTION_OUTCOMES:
            data = entry["data"]
            key = (data.get("jti"), data.get("action"))
            last_outcome[key] = ACTION_OUTCOMES[entry["event"]]
    evidence.outcomes = Counter(last_outcome.values())
    return evidence


def reconstruct(run_id, state_dir):
    """Rebuild one run from the domain ledgers under state_dir."""
    state_dir = Path(state_dir)
    domains = [
        _rebuild_domain(domain, state_dir / domain / LEDGER_NAME, run_id)
        for domain in DOMAINS
    ]
    return Rebuild(run_id, domains)


def format_rebuild(rebuild):
    """Return the report lines for one rebuild, ASCII only."""
    lines = ["run id: " + rebuild.run_id]
    lines.append("%-11s %-9s %-8s %-7s %-15s %s" % (
        "domain", "executed", "refused", "failed", "token_rejected", "chain"))
    totals = Counter()
    for evidence in rebuild.domains:
        if evidence.chain_ok:
            counts = [evidence.outcomes[outcome] for outcome in OUTCOMES]
            totals.update(evidence.outcomes)
            chain = "ok"
        else:
            counts = ["-"] * len(OUTCOMES)
            chain = "BROKEN: " + evidence.chain_error
        lines.append("%-11s %-9s %-8s %-7s %-15s %s" % (
            evidence.domain, counts[0], counts[1], counts[2],
            evidence.rejected if evidence.chain_ok else "-", chain))
    if rebuild.chain_ok:
        lines.append("total: executed %d  refused %d  failed %d  token_rejected %d" % (
            totals["executed"], totals["refused"], totals["failed"],
            sum(evidence.rejected for evidence in rebuild.domains)))
        if not any(totals.values()) and not any(
                evidence.rejected for evidence in rebuild.domains):
            lines.append("no ledger lines carry this run id")
    else:
        lines.append("not verified: at least one domain chain is broken; its lines are not counted")
    lines.extend(LIMITS)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m ledger.reconstruct",
        description="Rebuild one run from the three domain ledgers (read-only).",
    )
    parser.add_argument("run_id")
    parser.add_argument("--state-dir", default=None,
                        help="folder holding the domain ledgers (default OC_STATE_DIR or ./state)")
    args = parser.parse_args(argv)
    state_dir = args.state_dir or os.environ.get("OC_STATE_DIR", "state")
    rebuild = reconstruct(args.run_id, state_dir)
    for line in format_rebuild(rebuild):
        print(line)
    return 0 if rebuild.chain_ok else 1


if __name__ == "__main__":
    sys.exit(main())
