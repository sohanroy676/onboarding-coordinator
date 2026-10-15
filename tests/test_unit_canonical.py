import unittest

from coordinator.planner import canonical_json, plan_hash


class CanonicalJsonTests(unittest.TestCase):
    def test_key_order_does_not_matter(self):
        a = {"b": 1, "a": [1, 2], "c": {"y": 1, "x": 2}}
        b = {"c": {"x": 2, "y": 1}, "a": [1, 2], "b": 1}
        self.assertEqual(canonical_json(a), canonical_json(b))

    def test_no_whitespace(self):
        self.assertEqual(canonical_json({"a": [1, 2]}), b'{"a":[1,2]}')

    def test_non_ascii_is_escaped(self):
        out = canonical_json({"name": "Zo\u00eb"})
        self.assertEqual(out, b'{"name":"Zo\\u00eb"}')
        out.decode("ascii")

    def test_nan_and_infinity_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                canonical_json({"x": bad})

    def test_non_json_type_rejected(self):
        with self.assertRaises(TypeError):
            canonical_json({"x": {1, 2}})

    def test_list_order_is_significant(self):
        self.assertNotEqual(canonical_json([1, 2]), canonical_json([2, 1]))


class PlanHashTests(unittest.TestCase):
    PLAN = {
        "hire": "alice",
        "steps": [
            {"domain": "hr", "action": "create_record"},
            {"domain": "it", "action": "create_account"},
        ],
    }

    def test_stable_and_hex_sha256(self):
        first = plan_hash(self.PLAN)
        self.assertEqual(first, plan_hash(dict(reversed(list(self.PLAN.items())))))
        self.assertEqual(len(first), 64)
        int(first, 16)

    def test_known_vector(self):
        self.assertEqual(
            plan_hash({}),
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        )

    def test_any_field_change_changes_hash(self):
        base = plan_hash(self.PLAN)
        changed = {
            "hire": "alice",
            "steps": [
                {"domain": "hr", "action": "create_record"},
                {"domain": "it", "action": "grant_admin_access"},
            ],
        }
        self.assertNotEqual(base, plan_hash(changed))
        reordered = {"hire": "alice", "steps": list(reversed(self.PLAN["steps"]))}
        self.assertNotEqual(base, plan_hash(reordered))


if __name__ == "__main__":
    unittest.main()
