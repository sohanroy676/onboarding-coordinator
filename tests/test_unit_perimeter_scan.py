"""Unit tests for the G6 scanner. Samples are built at run time so that no
secret-shaped literal ever sits in a project file."""

import tempfile
import unittest
from pathlib import Path

from tests.perimeter_scan import (
    FIXTURE_SECRETS,
    changed_paths,
    scan_imports,
    scan_secrets,
    snapshot,
    write_sites,
)


def write_tree(files):
    """Write {relative path: text} under a new temp dir and return its Path."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text if isinstance(text, bytes) else text.encode("ascii"))
    return tmp, root


class SecretRules(unittest.TestCase):
    def rules_for(self, line):
        tmp, root = write_tree({"a.md": line + "\n"})
        self.addCleanup(tmp.cleanup)
        return {finding.rule for finding in scan_secrets(root)}

    def test_quoted_secret_literal_is_flagged(self):
        self.assertIn("secret-named literal",
                      self.rules_for('EXCHANGE_SECRET = "' + "z" * 30 + '"'))

    def test_json_style_token_is_flagged(self):
        self.assertIn("secret-named literal",
                      self.rules_for('"token": "' + "y" * 30 + '"'))

    def test_oc_secret_assignment_is_flagged(self):
        self.assertIn("oc secret assignment",
                      self.rules_for("OC_EXCHANGE_SECRET=" + "a1" * 32))

    def test_private_key_block_is_flagged(self):
        self.assertIn("private key block",
                      self.rules_for("-----BEGIN " + "RSA PRIVATE KEY-----"))

    def test_access_key_shape_is_flagged(self):
        self.assertIn("cloud access key", self.rules_for("id " + "AKIA" + "A" * 16))

    def test_token_shaped_string_is_flagged(self):
        self.assertIn("token-shaped string",
                      self.rules_for("eyJ" + "a" * 12 + "." + "b" * 12))

    def test_ordinary_code_is_not_flagged(self):
        self.assertEqual(self.rules_for("token = secrets.token_hex(32)"), set())
        self.assertEqual(self.rules_for('APPROVAL_SECRET = "short"'), set())

    def test_fixture_placeholder_is_exempt_by_exact_value(self):
        self.assertEqual(self.rules_for('SECRET = "%s"' % FIXTURE_SECRETS[0]), set())

    def test_near_miss_of_a_fixture_value_is_still_flagged(self):
        near = FIXTURE_SECRETS[0] + "-x"
        self.assertIn("secret-named literal", self.rules_for('SECRET = "%s"' % near))

    def test_state_folder_and_binary_files_do_not_crash_the_scan(self):
        bad = b"\xff\xfe" + "OC_DOMAIN_KEY=".encode("ascii") + b"ab" * 32
        planted = "OC_DOMAIN_KEY=" + "ab" * 32
        tmp, root = write_tree({
            "state/hr/notes.md": planted,
            "data.txt": bad,
        })
        self.addCleanup(tmp.cleanup)
        findings = scan_secrets(root)
        self.assertEqual([f.path for f in findings], ["data.txt"])


class WriteSiteRules(unittest.TestCase):
    def sites(self, source):
        tmp, root = write_tree({"m.py": source})
        self.addCleanup(tmp.cleanup)
        return [kind for _line, kind in write_sites(root / "m.py")]

    def test_builtin_open_modes(self):
        self.assertEqual(self.sites('open(p, "a")\n'), ["open:a"])
        self.assertEqual(self.sites('open(p, mode="x")\n'), ["open:x"])
        self.assertEqual(self.sites('open(p)\n'), [])
        self.assertEqual(self.sites('open(p, "r")\n'), [])

    def test_non_literal_builtin_mode_is_reported(self):
        self.assertEqual(self.sites("open(p, m)\n"), ["open:?"])

    def test_path_open_read_is_not_a_write(self):
        self.assertEqual(self.sites('p.open("r", encoding="ascii")\n'), [])

    def test_path_open_write_is_a_write(self):
        self.assertEqual(self.sites('p.open("a")\n'), ["open:a"])

    def test_method_open_without_mode_is_not_a_file_write(self):
        self.assertEqual(self.sites("opener.open(request, timeout=5)\n"), [])

    def test_path_open_with_non_literal_mode_is_reported(self):
        self.assertEqual(self.sites("p.open(m, encoding='ascii')\n"), ["open:?"])

    def test_path_open_with_non_literal_keyword_mode_is_reported(self):
        self.assertEqual(self.sites("p.open(mode=m)\n"), ["open:?"])

    def test_non_literal_mode_on_read_only_opener_is_not_reported(self):
        self.assertEqual(self.sites("opener.open(m, timeout=5)\n"), [])

    def test_path_open_with_no_arguments_is_not_reported(self):
        self.assertEqual(self.sites("p.open()\n"), [])

    def test_mutating_calls_are_listed(self):
        self.assertEqual(self.sites("p.mkdir(parents=True)\np.unlink()\n"),
                         ["mkdir", "unlink"])


class SnapshotRules(unittest.TestCase):
    def test_added_changed_and_removed_paths_are_reported(self):
        tmp, root = write_tree({"a.txt": "one", "b.txt": "two"})
        self.addCleanup(tmp.cleanup)
        before = snapshot(root)
        (root / "a.txt").write_text("changed", encoding="ascii")
        (root / "b.txt").unlink()
        (root / "c.txt").write_text("new", encoding="ascii")
        self.assertEqual(changed_paths(before, snapshot(root)),
                         {"a.txt", "b.txt", "c.txt"})

    def test_same_size_rewrite_is_still_a_change(self):
        tmp, root = write_tree({"a.txt": "aaaa"})
        self.addCleanup(tmp.cleanup)
        before = snapshot(root)
        (root / "a.txt").write_text("bbbb", encoding="ascii")
        self.assertEqual(changed_paths(before, snapshot(root)), {"a.txt"})

    def test_missing_folder_has_an_empty_snapshot(self):
        self.assertEqual(snapshot(Path(tempfile.gettempdir()) / "no-such-oc-dir"), {})


class AppImportRules(unittest.TestCase):
    """app/ may use coordinator and ledger.reconstruct, never domains or ledger.ledger."""

    def findings_for(self, module_text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "bad.py").write_text(module_text, encoding="ascii")
            return sorted(f.rule for f in scan_imports(root))

    def test_planted_domains_import_from_app_is_flagged(self):
        self.assertEqual(self.findings_for("from domains import hr_agent\n"),
                         ["import domains from app"])

    def test_planted_ledger_internals_import_from_app_is_flagged(self):
        self.assertEqual(self.findings_for("import ledger.ledger\n"),
                         ["import ledger.ledger from app"])
        self.assertEqual(self.findings_for("from ledger.ledger import read_entries\n"),
                         ["import ledger.ledger from app"])

    def test_allowed_imports_from_app_are_not_flagged(self):
        text = ("import coordinator.run\n"
                "from ledger.reconstruct import reconstruct\n"
                "import provision\n"
                "import demo\n")
        self.assertEqual(self.findings_for(text), [])


if __name__ == "__main__":
    unittest.main()
