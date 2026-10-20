#!/usr/bin/env python3
"""Risk tier for a PR: which review depth it needs (suu-itadm/.github#5).

    risk_tier.py match --rules RULES.json --diff PR.diff --template prompt.md
        Matches the diff against the repo's rules. Prints `deep`, `matched` and
        `prompt` as GitHub step outputs (to $GITHUB_OUTPUT when set).

    risk_tier.py tier --deep true|false < comment.md
        Prints the tier to label: the one in the comment's "Review depth" line,
        or `deep` when the rules matched or the line is missing.
"""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

CATEGORIES = (
    "schema",
    "auth",
    "system-of-record",
    "money",
    "student-records",
    "raw-sql",
    "unsafe-output",
    "secrets-config",
    "ci-deploy",
    "scheduled",
)
TIERS = ("skim", "intent", "deep")
MAX_LISTED = 15


def glob_to_regex(pattern):
    """`**` spans directories, `*` and `?` stay within one path segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def load_rules(data):
    """Validates the rules and compiles their globs. Unknown categories are an
    error so every repo keeps the shared vocabulary."""
    data = data or {}
    unknown = set(data.get("categories", {})) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown categories: {', '.join(sorted(unknown))}")
    return {
        "ignore": [glob_to_regex(g) for g in data.get("ignore", [])],
        "categories": {
            name: {
                "paths": [(g, glob_to_regex(g)) for g in rule.get("paths", [])],
                "lines": list(rule.get("lines", [])),
            }
            for name, rule in data.get("categories", {}).items()
        },
    }


def parse_diff(text):
    """Yields (path, added and removed lines) per file. Git names a deleted file
    `b/<old path>` too, so the b-side path covers adds, edits, renames and deletes.
    Lines before a file's first hunk are headers (`--- a/x`), not content."""
    path, lines, in_hunk = None, [], False
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            if path is not None:
                yield path, lines
            m = re.match(r"diff --git a/.* b/(.*)", raw)
            path, lines, in_hunk = (m.group(1) if m else raw[11:]), [], False
        elif raw.startswith("@@"):
            in_hunk = True
        elif in_hunk and raw[:1] in "+-":
            lines.append(raw[1:])
    if path is not None:
        yield path, lines


def match(rules, diff_text):
    """Every (category, file, rule) the diff hits, path rules first."""
    hits, seen = [], set()
    for path, lines in parse_diff(diff_text):
        if any(rx.match(path) for rx in rules["ignore"]):
            continue
        for name, rule in rules["categories"].items():
            for glob, rx in rule["paths"]:
                if rx.match(path) and (name, path, glob) not in seen:
                    seen.add((name, path, glob))
                    hits.append({"category": name, "file": path, "rule": glob})
            for needle in rule["lines"]:
                if (name, path, needle) not in seen and any(needle in ln for ln in lines):
                    seen.add((name, path, needle))
                    hits.append({"category": name, "file": path, "rule": needle})
    return hits


def summarize(hits):
    """Markdown bullets for the prompt and the comment."""
    if not hits:
        return "None."
    rows = [f"- `{h['category']}`: `{h['file']}` matched `{h['rule']}`" for h in hits[:MAX_LISTED]]
    if len(hits) > MAX_LISTED:
        rows.append(f"- …and {len(hits) - MAX_LISTED} more")
    return "\n".join(rows)


def tier_from_comment(text, deep):
    if deep:
        return "deep"
    m = re.search(r"Review depth:\W*(skim|intent|deep)\b", text, re.IGNORECASE)
    return m.group(1).lower() if m else "deep"


def write_outputs(outputs):
    """Multi-line values use a random heredoc delimiter, per the Actions docs."""
    text = ""
    for key, value in outputs.items():
        delim = f"EOF_{uuid.uuid4().hex}"
        text += f"{key}<<{delim}\n{value}\n{delim}\n"
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match")
    m.add_argument("--rules", type=Path, help="rules as JSON; missing file = no rules")
    m.add_argument("--diff", type=Path, required=True)
    m.add_argument("--template", type=Path, required=True)
    m.add_argument("--unchecked", metavar="REASON", help="the diff couldn't be read: force deep")
    t = sub.add_parser("tier")
    t.add_argument("--deep", choices=("true", "false"), required=True)
    args = parser.parse_args(argv)

    if args.cmd == "tier":
        print(tier_from_comment(sys.stdin.read(), args.deep == "true"))
        return 0

    data = json.loads(args.rules.read_text()) if args.rules and args.rules.exists() else {}
    hits = match(load_rules(data), args.diff.read_text(errors="replace"))
    if args.unchecked:
        hits.insert(0, {"category": "unchecked", "file": "(whole PR)", "rule": args.unchecked})
    matched = summarize(hits)
    write_outputs({
        "deep": "true" if hits else "false",
        "matched": matched,
        "prompt": args.template.read_text().replace("{{MATCHED}}", matched),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
