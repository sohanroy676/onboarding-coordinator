"""Keep the checklist and the review guide honest: every cited test and trace exists."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = ROOT / "docs" / "acceptance-checklist.md"
REVIEW_GUIDE = ROOT / "docs" / "review-guide.md"
TEST_REF = re.compile(r"(test_(?:g\d|unit)_\w+)\.(?:(\w+)\.)?(test_\w+)")
TRACE_REF = re.compile(r"traces/[\w.-]+\.txt")


def find_missing(text):
    """Return a list of problems: cited tests or traces that do not exist."""
    problems = []
    for module, cls, method in TEST_REF.findall(text):
        path = ROOT / "tests" / (module + ".py")
        if not path.is_file():
            problems.append("no module " + module)
            continue
        source = path.read_text(encoding="utf-8")
        if "def " + method + "(" not in source:
            problems.append("no test " + module + "." + method)
        if cls and not re.search(r"class " + cls + r"\b", source):
            problems.append("no class " + module + "." + cls)
    for trace in set(TRACE_REF.findall(text)):
        if not (ROOT / trace).is_file():
            problems.append("no trace " + trace)
    return problems


class AcceptanceChecklistTest(unittest.TestCase):

    def setUp(self):
        self.text = CHECKLIST.read_text(encoding="utf-8")

    def test_checklist_cites_enough_tests(self):
        self.assertGreater(len(TEST_REF.findall(self.text)), 10)

    def test_every_cited_test_and_trace_exists(self):
        self.assertEqual(find_missing(self.text), [])

    def test_planted_missing_test_is_reported(self):
        text = "`test_g1_domains_registry.test_not_a_real_test`"
        self.assertEqual(find_missing(text), ["no test test_g1_domains_registry.test_not_a_real_test"])

    def test_planted_missing_module_is_reported(self):
        text = "`test_g9_nothing.test_anything`"
        self.assertEqual(find_missing(text), ["no module test_g9_nothing"])

    def test_planted_missing_trace_is_reported(self):
        text = "see traces/v0-0-nothing.txt"
        self.assertEqual(find_missing(text), ["no trace traces/v0-0-nothing.txt"])

    def test_planted_missing_unit_test_is_reported(self):
        text = "`test_unit_app_onboarding.NoSuchClass.test_y_in_any_case_approves_and_runs`"
        self.assertEqual(find_missing(text),
                         ["no class test_unit_app_onboarding.NoSuchClass"])

    def test_planted_missing_class_is_reported(self):
        text = "`test_g6_perimeters.NoSuchClass.test_reconstruct_is_read_only`"
        self.assertEqual(find_missing(text), ["no class test_g6_perimeters.NoSuchClass"])


class ReviewGuideTest(unittest.TestCase):

    def setUp(self):
        self.text = REVIEW_GUIDE.read_text(encoding="utf-8")

    def test_guide_cites_traces(self):
        self.assertGreater(len(set(TRACE_REF.findall(self.text))), 5)

    def test_every_cited_test_and_trace_exists(self):
        self.assertEqual(find_missing(self.text), [])

    def test_guide_is_ascii(self):
        self.text.encode("ascii")

    def test_planted_missing_trace_in_guide_text_is_reported(self):
        text = self.text + " see traces/final-audit-nothing.txt"
        self.assertEqual(find_missing(text), ["no trace traces/final-audit-nothing.txt"])


if __name__ == "__main__":
    unittest.main()
