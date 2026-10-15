"""Static and snapshot checks for gate G6: credentials, imports and writes.

Used by tests/test_g6_perimeters.py and tests/test_unit_perimeter_scan.py.
Standard library only and read-only: nothing here writes into the project.
The scanner lives in tests/ so the three source folders keep their file budget.
"""

import ast
import hashlib
import re
from collections import Counter, namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FOLDERS = ("domains", "coordinator", "ledger")
ROOT_SCRIPTS = ("provision.py", "demo.py")
TEXT_SUFFIXES = frozenset({".py", ".md", ".txt", ".json", ".yml", ".yaml"})
SKIP_DIRS = frozenset({"state", ".git", "__pycache__"})

Finding = namedtuple("Finding", "path line rule")

# Placeholder values the unit tests use as fake secrets. They are not
# credentials; each is matched by exact value, so any other secret-shaped
# literal still fails the scan.
FIXTURE_SECRETS = (
    "unit-test-exchange-secret",
    "unit-run-exchange-secret",
    "unit-run-approval-secret",
)

SECRET_RULES = (
    ("secret-named literal",
     re.compile(r"""(?i)\w*(secret|token|passw(or)?d|api_?key)\w*["']?\s*[:=]\s*["'][A-Za-z0-9+/_\-=]{24,}["']""")),
    ("oc secret assignment",
     re.compile(r"OC_\w*(SECRET|KEY)\w*\s*=\s*[0-9a-fA-F]{32,}")),
    ("private key block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cloud access key",
     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token-shaped string",
     re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)

# Write-like calls in the scanned code. Mode strings containing w, a, x or +
# count as writes. An unknown mode (not a literal) is reported as open:?.
WRITE_METHODS = frozenset({
    "write_text", "write_bytes", "mkdir", "makedirs", "touch", "unlink",
    "remove", "rmdir", "rename",
})
WRITE_MODE = re.compile(r"[wax+]")

# Every write site the project is allowed to have, as (file, kind) -> count.
# Anything else found by write_sites() fails the G6 static check.
ALLOWED_WRITES = Counter({
    ("coordinator/approval.py", "mkdir"): 1,
    ("coordinator/approval.py", "open:x"): 1,
    ("coordinator/tokens.py", "mkdir"): 1,
    ("coordinator/tokens.py", "open:a"): 1,
    ("ledger/ledger.py", "mkdir"): 1,
    ("ledger/ledger.py", "open:a"): 1,
})

# Which top-level packages each source folder may import.
FORBIDDEN_IMPORTS = {
    "domains": frozenset({"coordinator"}),
    "coordinator": frozenset({"domains", "ledger"}),
    "ledger": frozenset({"coordinator", "domains"}),
}
HMAC_IMPORTERS = frozenset({"coordinator/tokens.py", "domains/domain_agent.py"})


def _relpath(path, root):
    return path.relative_to(root).as_posix()


def _text_files(root):
    """Yield project text files under root, skipping runtime and VCS folders."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        yield path


def _is_fixture(line, value):
    """True when the line quotes exactly one fixture placeholder."""
    return ('"%s"' % value) in line or ("'%s'" % value) in line


def scan_secrets(root=ROOT):
    """Return a Finding for every line under root that matches a secret rule."""
    findings = []
    for path in _text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if any(_is_fixture(line, value) for value in FIXTURE_SECRETS):
                continue
            for rule, pattern in SECRET_RULES:
                if pattern.search(line):
                    findings.append(Finding(_relpath(path, root), number, rule))
    return findings


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _source_files(root):
    for folder in SOURCE_FOLDERS:
        yield from sorted((root / folder).glob("*.py"))
    for script in ROOT_SCRIPTS:
        if (root / script).is_file():
            yield root / script


def imported_names(path):
    """Return the top-level package names that a module imports."""
    names = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def scan_imports(root=ROOT):
    """Return a Finding for each forbidden cross-package or hmac import."""
    findings = []
    for folder, forbidden in FORBIDDEN_IMPORTS.items():
        for path in sorted((root / folder).glob("*.py")):
            for name in sorted(imported_names(path) & forbidden):
                rule = "import %s from %s" % (name, folder)
                findings.append(Finding(_relpath(path, root), 0, rule))
    for path in _source_files(root):
        rel = _relpath(path, root)
        if "hmac" in imported_names(path) and rel not in HMAC_IMPORTERS:
            findings.append(Finding(rel, 0, "import hmac outside verifier and minter"))
    return findings


def _mode_of(call, is_method):
    """Return the mode of an open() call: a literal string, "?" if not literal,
    or None when a method open has no mode (e.g. urllib's opener.open(request)
    or Path.open()), which is not a file write."""
    position = 0 if is_method else 1
    if len(call.args) > position:
        node = call.args[position]
    else:
        node = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
        if node is None:
            return None if is_method else "r"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None if is_method else "?"


def write_sites(path):
    """Return sorted (line, kind) for every call in path that can change files."""
    sites = []
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_method = isinstance(func, ast.Attribute)
        name = func.attr if is_method else getattr(func, "id", None)
        if name == "open":
            mode = _mode_of(node, is_method)
            if mode is not None and (mode == "?" or WRITE_MODE.search(mode)):
                sites.append((node.lineno, "open:" + mode))
        elif name in WRITE_METHODS:
            sites.append((node.lineno, name))
    return sorted(sites)


def scan_writes(root=ROOT):
    """Return the write sites found, as a Counter of (file, kind)."""
    found = Counter()
    for path in _source_files(root):
        for _line, kind in write_sites(path):
            found[(_relpath(path, root), kind)] += 1
    return found


def scan_coordinator_env(root=ROOT):
    """Return a Finding for any env read or domain-key name in coordinator/."""
    findings = []
    for path in sorted((root / "coordinator").glob("*.py")):
        rel = _relpath(path, root)
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                findings.append(Finding(rel, node.lineno, "environment read"))
            if isinstance(node, ast.Constant) and node.value == "OC_DOMAIN_KEY":
                findings.append(Finding(rel, node.lineno, "domain key name"))
    return findings


def snapshot(folder):
    """Return {relative posix path: sha256 hex} for every file under folder."""
    if not folder.is_dir():
        return {}
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[_relpath(path, folder)] = digest
    return result


def changed_paths(before, after):
    """Return the set of paths added, removed or changed between two snapshots."""
    keys = set(before) | set(after)
    return {key for key in keys if before.get(key) != after.get(key)}
