"""Unit tests for app/model_planner.py: the .env reader, the client and the parser.

No network: the client gets an injected transport. Key-shaped values are built
at run time so no project file holds one.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.model_planner import (
    API_URL,
    DEFAULT_MODEL,
    GrokClient,
    MAX_PROPOSAL_CHARS,
    MAX_REPLY_BYTES,
    ModelPlannerError,
    build_system_prompt,
    parse_proposal,
    read_key,
)

FAKE_KEY = "unit-" + "k" * 30


def reply_body(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


class FakeTransport:
    def __init__(self, status=200, raw=None, error=None):
        self.status = status
        self.raw = reply_body("{}") if raw is None else raw
        self.error = error
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body.decode("utf-8")), timeout))
        if self.error:
            raise self.error
        return self.status, self.raw


class ReadKeyTests(unittest.TestCase):
    def read(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / ".env"
        if data is not None:
            path.write_bytes(data if isinstance(data, bytes) else data.encode("ascii"))
        return read_key(path)

    def test_plain_key_is_returned(self):
        self.assertEqual(self.read("XAI_API_KEY=%s\n" % FAKE_KEY), FAKE_KEY)

    def test_comments_blanks_and_other_names_are_skipped(self):
        text = "# note\n\nOTHER=1\n  XAI_API_KEY = %s  \n" % FAKE_KEY
        self.assertEqual(self.read(text), FAKE_KEY)

    def test_equals_sign_inside_the_value_is_kept(self):
        self.assertEqual(self.read("XAI_API_KEY=ab=cd\n"), "ab=cd")

    def test_missing_file_is_an_error(self):
        with self.assertRaisesRegex(ModelPlannerError, "no .env file"):
            self.read(None)

    def test_missing_key_or_empty_value_is_an_error(self):
        for text in ("OTHER=1\n", "XAI_API_KEY=\n", ""):
            with self.subTest(text=text), self.assertRaisesRegex(
                    ModelPlannerError, "no value for XAI_API_KEY"):
                self.read(text)

    def test_line_without_equals_is_an_error_naming_only_the_line(self):
        with self.assertRaisesRegex(ModelPlannerError, "line 2 is not KEY=VALUE"):
            self.read("XAI_API_KEY=%s\nbroken\n" % FAKE_KEY)

    def test_non_ascii_and_oversized_files_are_refused(self):
        with self.assertRaisesRegex(ModelPlannerError, "ASCII"):
            self.read("XAI_API_KEY=café\n".encode("utf-8"))
        with self.assertRaisesRegex(ModelPlannerError, "larger than"):
            self.read("# " + "x" * 5000 + "\n")

    def test_errors_never_contain_the_key(self):
        try:
            self.read("XAI_API_KEY=%s\nbroken\n" % FAKE_KEY)
        except ModelPlannerError as exc:
            self.assertNotIn(FAKE_KEY, str(exc))


class ClientTests(unittest.TestCase):
    def client(self, transport):
        return GrokClient(FAKE_KEY, transport=transport)

    def test_request_shape(self):
        transport = FakeTransport(raw=reply_body("hello"))
        text = self.client(transport).propose("system", "user words")
        self.assertEqual(text, "hello")
        self.assertEqual(len(transport.calls), 1)
        url, headers, body, _timeout = transport.calls[0]
        self.assertEqual(url, API_URL)
        self.assertEqual(headers["Authorization"], "Bearer " + FAKE_KEY)
        self.assertEqual(body["model"], DEFAULT_MODEL)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(body["messages"][1]["content"], "user words")
        schema = body["response_format"]["json_schema"]
        self.assertTrue(schema["strict"])
        self.assertEqual(schema["schema"]["required"], ["requests"])
        self.assertNotIn(FAKE_KEY, json.dumps(body))

    def test_rate_limit_is_reported_and_not_retried(self):
        transport = FakeTransport(status=429)
        with self.assertRaisesRegex(ModelPlannerError, "rate limit"):
            self.client(transport).propose("s", "u")
        self.assertEqual(len(transport.calls), 1)

    def test_other_statuses_and_transport_errors_are_reported(self):
        cases = [FakeTransport(status=500), FakeTransport(status=401),
                 FakeTransport(error=OSError("boom " + FAKE_KEY)),
                 FakeTransport(error=TimeoutError("slow"))]
        for transport in cases:
            with self.subTest(status=transport.status, error=transport.error):
                with self.assertRaises(ModelPlannerError) as ctx:
                    self.client(transport).propose("s", "u")
                self.assertNotIn(FAKE_KEY, str(ctx.exception))
                self.assertEqual(len(transport.calls), 1)

    def test_odd_reply_shapes_are_reported(self):
        for raw in (b"not json", b"{}", b'{"choices": []}',
                    json.dumps({"choices": [{"message": {"content": 5}}]}).encode(),
                    b"x" * (MAX_REPLY_BYTES + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(ModelPlannerError):
                self.client(FakeTransport(raw=raw)).propose("s", "u")

    def test_no_key_is_refused(self):
        with self.assertRaises(ModelPlannerError):
            GrokClient("")


class PromptTests(unittest.TestCase):
    def test_prompt_lists_only_the_offered_actions(self):
        prompt = build_system_prompt({"hr": ["create_record"], "it": ["assign_laptop"],
                                      "facilities": []})
        self.assertIn("hr: create_record", prompt)
        self.assertIn("it: assign_laptop", prompt)
        self.assertNotIn("grant_admin_access", prompt)


class ParseProposalTests(unittest.TestCase):
    def doc(self, items):
        return json.dumps({"requests": items})

    def test_valid_proposal(self):
        text = self.doc([{"domain": "it", "action": "create_account"},
                         {"domain": "hr", "action": "create_record"}])
        self.assertEqual(parse_proposal(text), ["it:create_account", "hr:create_record"])

    def test_bad_shapes_are_refused(self):
        item = {"domain": "it", "action": "create_account"}
        cases = {
            "not json": "nope",
            "array": "[]",
            "extra top-level field": json.dumps({"requests": [item], "subject": "x@y"}),
            "no requests": "{}",
            "empty list": self.doc([]),
            "thirteen items": self.doc([item] * 13),
            "not a list": json.dumps({"requests": item}),
            "extra item field": self.doc([dict(item, params={"a": 1})]),
            "missing field": self.doc([{"domain": "it"}]),
            "non-string": self.doc([{"domain": "it", "action": 5}]),
            "item not an object": self.doc(["it:create_account"]),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(ModelPlannerError):
                parse_proposal(text)

    def test_twelve_items_are_accepted(self):
        item = {"domain": "it", "action": "create_account"}
        self.assertEqual(len(parse_proposal(self.doc([item] * 12))), 12)

    def test_oversized_and_non_string_input_is_refused(self):
        padding = {"domain": "it", "action": "a" * MAX_PROPOSAL_CHARS}
        with self.assertRaisesRegex(ModelPlannerError, "longer than"):
            parse_proposal(self.doc([padding]))
        with self.assertRaises(ModelPlannerError):
            parse_proposal(None)


if __name__ == "__main__":
    unittest.main()
