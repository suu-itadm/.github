import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import risk_tier as rt

HERE = Path(__file__).parent


def diff(path, *lines, old=None):
    """A minimal git diff for one file; `old` makes it a rename."""
    body = "\n".join(lines)
    return (
        f"diff --git a/{old or path} b/{path}\n"
        f"--- a/{old or path}\n+++ b/{path}\n@@ -1,3 +1,3 @@\n {'context'}\n{body}\n"
    )


RULES = rt.load_rules({
    "ignore": ["**/tests/**"],
    "categories": {
        "schema": {"paths": ["**/migrations/**"]},
        "raw-sql": {"lines": [".raw(", "cursor("]},
        "secrets-config": {"paths": ["config/*.py"]},
        "auth": {"paths": ["**/mixins.py"]},
    },
})


class GlobTests(unittest.TestCase):
    def test_double_star_spans_directories(self):
        rx = rt.glob_to_regex("**/migrations/**")
        self.assertTrue(rx.match("portal/hr/migrations/0001_initial.py"))
        self.assertTrue(rx.match("migrations/0001.py"))
        self.assertFalse(rx.match("portal/hr/migrationsx/0001.py"))

    def test_single_star_stays_in_segment(self):
        rx = rt.glob_to_regex("config/*.py")
        self.assertTrue(rx.match("config/settings.py"))
        self.assertFalse(rx.match("config/sub/settings.py"))

    def test_dots_are_literal(self):
        self.assertFalse(rt.glob_to_regex("**/mixins.py").match("portal/mixinsXpy"))


class MatchTests(unittest.TestCase):
    def test_path_match(self):
        hits = rt.match(RULES, diff("portal/hr/migrations/0002_x.py", "+x = 1"))
        self.assertEqual(hits, [{"category": "schema", "file": "portal/hr/migrations/0002_x.py",
                                 "rule": "**/migrations/**"}])

    def test_added_line_match(self):
        hits = rt.match(RULES, diff("portal/hr/views.py", "+rows = Model.objects.raw(sql)"))
        self.assertEqual([h["category"] for h in hits], ["raw-sql"])

    def test_removed_line_counts(self):
        hits = rt.match(RULES, diff("portal/hr/views.py", "-c = connection.cursor()"))
        self.assertEqual([h["rule"] for h in hits], ["cursor("])

    def test_context_lines_dont_count(self):
        self.assertEqual(rt.match(RULES, diff("portal/hr/views.py", " x.raw(sql)", "+y = 1")), [])

    def test_header_lines_dont_count(self):
        # A path containing a pattern shows up in `--- a/` headers, not content.
        text = diff("portal/cursor(/views.py", "+y = 1")
        self.assertEqual(rt.match(RULES, text), [])

    def test_no_match(self):
        self.assertEqual(rt.match(RULES, diff("portal/hr/views.py", "+return render(request)")), [])

    def test_ignored_paths_skip_every_rule(self):
        self.assertEqual(rt.match(RULES, diff("portal/hr/tests/test_views.py", "+x.raw(sql)")), [])

    def test_rename_uses_new_path(self):
        hits = rt.match(RULES, diff("portal/core/mixins.py", "+pass", old="portal/core/helpers.py"))
        self.assertEqual([h["category"] for h in hits], ["auth"])

    def test_several_files_and_one_hit_per_rule(self):
        text = diff("portal/a.py", "+x.raw(1)", "+y.raw(2)") + diff("config/settings.py", "+DEBUG = False")
        hits = rt.match(RULES, text)
        self.assertEqual([(h["category"], h["file"]) for h in hits],
                         [("raw-sql", "portal/a.py"), ("secrets-config", "config/settings.py")])

    def test_hunk_line_starting_with_dashes_is_content(self):
        hits = rt.match(RULES, diff("portal/a.py", "--- x.raw(1)"))
        self.assertEqual([h["rule"] for h in hits], [".raw("])


class RulesTests(unittest.TestCase):
    def test_unknown_category_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "pcard"):
            rt.load_rules({"categories": {"pcard": {"paths": ["x"]}}})

    def test_wrong_shapes_are_errors(self):
        bad = [
            ["schema"],
            {"categories": ["schema"]},
            {"categories": {"schema": ["**/migrations/**"]}},
            {"categories": {"schema": {"paths": "**/migrations/**"}}},
            {"ignore": "docs/**"},
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                rt.load_rules(data)

    def test_empty_rules_match_nothing(self):
        self.assertEqual(rt.match(rt.load_rules({}), diff("portal/hr/migrations/1.py", "+x")), [])
        self.assertEqual(rt.match(rt.load_rules(None), diff("portal/hr/migrations/1.py", "+x")), [])


class TierTests(unittest.TestCase):
    def test_reads_tier_from_comment(self):
        for word in rt.TIERS:
            self.assertEqual(rt.tier_from_comment(f"## Summary\n### Review depth: {word} 🟢\n", False), word)

    def test_emoji_before_word(self):
        self.assertEqual(rt.tier_from_comment("### Review depth: 🟡 intent", False), "intent")

    def test_rules_force_deep(self):
        self.assertEqual(rt.tier_from_comment("### Review depth: skim 🟢", True), "deep")

    def test_missing_line_is_deep(self):
        self.assertEqual(rt.tier_from_comment("no tier here", False), "deep")


class CliTests(unittest.TestCase):
    def run_match(self, rules, diff_text, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp, "pr.diff")
            d.write_text(diff_text)
            args = ["match", "--diff", str(d), "--template", str(HERE / "prompt.md"), *extra]
            if rules is not None:
                r = Path(tmp, "rules.json")
                r.write_text(json.dumps(rules))
                args += ["--rules", str(r)]
            # Read outputs the way Actions does, whatever the runner has set.
            out = Path(tmp, "github_output")
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}):
                rt.main(args)
            return out.read_text()

    def test_match_outputs_deep_and_prompt(self):
        out = self.run_match({"categories": {"schema": {"paths": ["**/migrations/**"]}}},
                             diff("app/migrations/1.py", "+x"))
        self.assertIn("deep<<EOF_", out)
        self.assertRegex(out, r"deep<<(EOF_\w+)\ntrue\n\1")
        self.assertIn("`schema`: `app/migrations/1.py` matched `**/migrations/**`", out)
        self.assertNotIn("{{MATCHED}}", out)

    def test_no_rules_file(self):
        out = self.run_match(None, diff("app/migrations/1.py", "+x"))
        self.assertRegex(out, r"deep<<(EOF_\w+)\nfalse\n\1")
        self.assertIn("None.", out)

    def test_unchecked_forces_deep(self):
        out = self.run_match(None, "", "--unchecked", "diff too large")
        self.assertRegex(out, r"deep<<(EOF_\w+)\ntrue\n\1")
        self.assertIn("matched `diff too large`", out)

    def test_invalid_rules_force_deep_instead_of_failing(self):
        out = self.run_match({"categories": {"pcard": {"paths": ["x"]}}}, diff("app/views.py", "+x"))
        self.assertRegex(out, r"deep<<(EOF_\w+)\ntrue\n\1")
        self.assertIn("invalid risk-tiers.yml: unknown categories: pcard", out)

    def test_every_unchecked_reason_is_listed(self):
        out = self.run_match(None, "", "--unchecked", "diff too large", "--unchecked", "bad YAML")
        self.assertIn("matched `diff too large`", out)
        self.assertIn("matched `bad YAML`", out)


if __name__ == "__main__":
    unittest.main()
