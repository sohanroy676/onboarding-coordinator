# ADR-0007: Perimeter checks as tests, not a linter

## Status
Accepted

## Date
2026-10-15

## Context
v0.8 must show gate G6: no credential literal in the project, no forbidden
import between the three folders, and no write outside the allowlist. The
project is standard-library only, so no linter or secret scanner can be added.
The three source folders must also keep exactly 11 files, so the checks cannot
live in a new module inside them.

## Decision
The checks run as unittest code. `tests/perimeter_scan.py` holds the scanners
(stdlib `ast` and `re`, read-only). `tests/test_g6_perimeters.py` runs them over
the real tree and over one in-process onboarding. Every static check has a
planted control that must be flagged, so a scanner that finds nothing is shown
to be able to find something. The write allowlist is an explicit table, and the
runtime check diffs a snapshot of `state/` around one run.

## Alternatives considered
- A third-party secret scanner or linter: not allowed (standard library only).
- A module in `coordinator/` or `domains/` for the scanner: breaks the 11-file
  rule and would put scanning code inside the components it checks.
- Regex-only import checks: the existing boundary tests in
  `test_unit_provision.py` already use regex; the AST scan also sees aliased and
  nested imports, so it is stricter.
- Trusting the directory listing for writes: a listing shows files, not which
  call created them. The static scan shows call sites; the snapshot shows effects.

## Consequences
- The checks are as strong as their rules. A credential in a form the rules do
  not match (for example a value split across two lines or built by string
  concatenation at run time) is not found. The planted control proves the rules
  fire on the shapes they claim to cover, not on every shape.
- Test fixture placeholders are exempt by exact quoted value only, listed in
  `FIXTURE_SECRETS`. Any new fixture that looks like a secret must be added there
  deliberately, which leaves a visible record.
- The write scan treats a non-literal mode on any method `open` as a write,
  except on the read-only `opener` (urllib, fix/write-scan-path-open). The runtime
  snapshot covers the in-process run only, not the child processes that
  `provision.py` starts.

## Limits the scan cannot prove
- **The coordinator can derive every domain key.** `TokenMinter` holds the
  exchange secret and calls `derive_domain_key` for each mint (`coordinator/tokens.py:88`).
  The G6 check proves that `coordinator/` never stores, reads from the
  environment, or names `OC_DOMAIN_KEY`. It does not prove the coordinator is
  unable to compute a domain key in memory. Closing that needs a different key
  design (per-domain keys held by the domains, with the coordinator signing with
  a key it cannot derive), and is left for a later decision. ADR-0008 accepts
  this as a stated limit for v1.
- Clock moving backwards, a deleted consumed marker re-opening replay, and
  truncation from the end of a hash chain (see ADR-0004 and ADR-0006) are not
  addressed here.
