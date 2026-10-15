# Changelog

All notable changes to this project are documented here.
Format follows Keep a Changelog. Generated from Conventional Commits — regenerate via `/commit` workflow, do not hand-edit.

## [Unreleased]

## [1.1.0] - 2026-10-15

Known-gap fixes after v1.0. Minor release: the token and approval formats changed.

### Changed
- Approvals carry `issued_at`; an approval used before its issue time is refused (ADR-0004).
- Tokens carry an `approval_id` claim; each domain refuses a reused approval (`approval_replayed`) and rebuilds that memory from its own ledger (ADR-0003, ADR-0004).
- The exchange counter is kept in a file, one line per exchange, and survives a coordinator restart (ADR-0006).

### Fixed
- The write scan flags `Path.open` with a non-literal mode as a write (`898bb49`).
- The provisioner kills a child that never reports READY and shows its stderr (`807fc60`).
- A clock moved backwards is refused for declarations and approvals instead of being treated as fresh (`9826566`).
- A deleted consumed-approval marker no longer re-opens replay at the domains (`27b0e7c`).

### Added
- Release evidence: fresh-clone checks and traces `traces/v1-1-*.txt` (`7b1ad88`).
- Gap-fix checklist section mapping each fix to its test and trace (`921e624`).

### Stated limits
- The coordinator can derive domain keys from the exchange secret (ADR-0007, ADR-0008).
- A clock rewound to a time still after `issued_at` extends an approval (ADR-0004).
- Someone with local administrator rights who deletes every approval marker and domain ledger can replay (ADR-0003, ADR-0004).
- The counter file and ledgers are local and not tamper-evident; the hash chain cannot detect truncation at the end (ADR-0006).

## [1.0.0]

- v1.0 freeze: fresh-checkout evidence, deliverables D1 to D12 mapped in the acceptance checklist, source archive (`d706058`).
