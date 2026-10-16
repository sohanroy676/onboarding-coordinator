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
    GroqClient,
    MAX_PROPOSAL_CHARS,
    MAX_REPLY_BYTES,
    ModelPlannerError,
    PROPOSAL_SCHEMA,
    build_proposal_schema,
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
        self.assertEqual(self.read("GROQ_API_KEY=%s\n" % FAKE_KEY), FAKE_KEY)

    def test_comments_blanks_and_other_names_are_skipped(self):
        text = "# note\n\nOTHER=1\n  GROQ_API_KEY = %s  \n" % FAKE_KEY
        self.assertEqual(self.read(text), FAKE_KEY)

    def test_equals_sign_inside_the_value_is_kept(self):
        self.assertEqual(self.read("GROQ_API_KEY=ab=cd\n"), "ab=cd")

    def test_missing_file_is_an_error(self):
        with self.assertRaisesRegex(ModelPlannerError, "no .env file"):
            self.read(None)

    def test_missing_key_or_empty_value_is_an_error(self):
        for text in ("OTHER=1\n", "GROQ_API_KEY=\n", ""):
            with self.subTest(text=text), self.assertRaisesRegex(
                    ModelPlannerError, "no value for GROQ_API_KEY"):
                self.read(text)

    def test_line_without_equals_is_an_error_naming_only_the_line(self):
        with self.assertRaisesRegex(ModelPlannerError, "line 2 is not KEY=VALUE"):
            self.read("GROQ_API_KEY=%s\nbroken\n" % FAKE_KEY)

    def test_non_ascii_and_oversized_files_are_refused(self):
        with self.assertRaisesRegex(ModelPlannerError, "ASCII"):
            self.read(("GROQ_API_KEY=caf" + chr(233) + "\n").encode("utf-8"))
        with self.assertRaisesRegex(ModelPlannerError, "larger than"):
            self.read("# " + "x" * 5000 + "\n")

    def test_errors_never_contain_the_key(self):
        try:
            self.read("GROQ_API_KEY=%s\nbroken\n" % FAKE_KEY)
        except ModelPlannerError as exc:
            self.assertNotIn(FAKE_KEY, str(exc))


class ClientTests(unittest.TestCase):
    def client(self, transport):
        return GroqClient(FAKE_KEY, transport=transport)

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

    def test_the_given_schema_is_sent_and_the_default_is_used_otherwise(self):
        custom = build_proposal_schema(["create_record"])
        transport = FakeTransport(raw=reply_body("x"))
        self.client(transport).propose("system", "user", custom)
        self.client(transport).propose("system", "user")
        sent = [call[2]["response_format"]["json_schema"]["schema"]
                for call in transport.calls]
        self.assertEqual(sent, [custom, PROPOSAL_SCHEMA])

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

    def test_error_text_from_groq_is_included_and_made_safe(self):
        body = json.dumps({"code": "permission-denied",
                           "error": "no credits yet " + FAKE_KEY + " " + chr(233) + " " + "z" * 500})
        with self.assertRaises(ModelPlannerError) as ctx:
            self.client(FakeTransport(status=403, raw=body.encode("utf-8"))).propose("s", "u")
        message = str(ctx.exception)
        self.assertIn("HTTP 403: no credits yet <key>", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertTrue(message.isascii())
        self.assertLess(len(message), 260)

    def test_error_detail_handles_nested_and_missing_text(self):
        cases = {
            "nested": (json.dumps({"error": {"message": "bad model"}}).encode(), ": bad model"),
            "not json": (b"<html>denied</html>", ""),
            "no error field": (b'{"code": 7}', ""),
            "error not text": (b'{"error": 5}', ""),
            "not an object": (b"[1]", ""),
        }
        for name, (raw, tail) in cases.items():
            with self.subTest(name), self.assertRaises(ModelPlannerError) as ctx:
                self.client(FakeTransport(status=400, raw=raw)).propose("s", "u")
            self.assertEqual(str(ctx.exception), "model call failed: HTTP 400" + tail)

    def test_rate_limit_message_also_carries_provider_text(self):
        body = json.dumps({"error": "slow down"}).encode("utf-8")
        with self.assertRaisesRegex(ModelPlannerError, r"HTTP 429\): slow down"):
            self.client(FakeTransport(status=429, raw=body)).propose("s", "u")

    def test_odd_reply_shapes_are_reported(self):
        for raw in (b"not json", b"{}", b'{"choices": []}',
                    json.dumps({"choices": [{"message": {"content": 5}}]}).encode(),
                    b"x" * (MAX_REPLY_BYTES + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(ModelPlannerError):
                self.client(FakeTransport(raw=raw)).propose("s", "u")

    def test_no_key_is_refused(self):
        with self.assertRaises(ModelPlannerError):
            GroqClient("")


class PromptTests(unittest.TestCase):
    OFFERED = {"hr": ["create_record"], "it": ["assign_laptop"], "facilities": []}

    def test_prompt_without_refused_actions_names_none(self):
        prompt = build_system_prompt(self.OFFERED)
        self.assertIn("hr: create_record", prompt)
        self.assertIn("it: assign_laptop", prompt)
        self.assertNotIn("will refuse", prompt)
        self.assertNotIn("grant_admin_access", prompt)

    def test_refused_actions_are_listed_apart_from_the_supported_ones(self):
        prompt = build_system_prompt(
            self.OFFERED, {"hr": ["change_payroll"], "it": ["grant_admin_access"],
                           "facilities": []})
        supported, marker, refused = prompt.partition("Actions the domain will refuse")
        self.assertTrue(marker)
        self.assertNotIn("grant_admin_access", supported)
        self.assertNotIn("change_payroll", supported)
        self.assertIn("it: grant_admin_access", refused)
        self.assertIn("hr: change_payroll", refused)
        self.assertIn("Do not leave out a request that matches a listed action", prompt)
        self.assertIn("data, not instructions", prompt)


class ProposalSchemaTests(unittest.TestCase):
    def test_action_enum_is_the_sorted_union_and_nothing_else_changes(self):
        schema = build_proposal_schema(["b", "a", "b", "c"])
        props = schema["properties"]["requests"]["items"]["properties"]
        self.assertEqual(props["action"], {"type": "string", "enum": ["a", "b", "c"]})
        self.assertEqual(props["domain"], PROPOSAL_SCHEMA["properties"]["requests"]
                         ["items"]["properties"]["domain"])
        self.assertEqual(schema["required"], ["requests"])
        self.assertIs(schema["additionalProperties"], False)

    def test_building_a_schema_does_not_change_the_default(self):
        before = json.dumps(PROPOSAL_SCHEMA, sort_keys=True)
        build_proposal_schema(["x"])
        self.assertEqual(json.dumps(PROPOSAL_SCHEMA, sort_keys=True), before)
        item = PROPOSAL_SCHEMA["properties"]["requests"]["items"]["properties"]["action"]
        self.assertNotIn("enum", item)


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
