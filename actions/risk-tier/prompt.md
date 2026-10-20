## Review Depth

Tell the human reviewer how closely this PR needs reading, and where to look. This goes at the very top of your comment, before "What This PR Does".

### Rules that matched

This repo's `.github/risk-tiers.yml` marks some files and code as sensitive. These matched this PR:

{{MATCHED}}

### Pick the tier

- If any rule matched above, the tier is **deep**. Don't pick a lower one.
- Otherwise:
  - **skim**: only comments, docstrings, docs, copy or text changes, CSS, formatting, or tests.
  - **intent**: logic changes that the PR's own tests exercise, and nothing that changes the database schema, who can see or do what, writes to Banner or another external system, money, student records, raw SQL, unescaped output, settings or secrets, CI or deploy, or scheduled jobs.
  - **deep**: anything else, or anything you aren't sure about. When in doubt, pick deep.

### Check the Merge Danger section

If the PR body has a `## Merge Danger` section (agent-loop PRs do), compare it against the diff. It **disagrees** when the diff contradicts it: for example "two-way" door when the PR adds a migration or changes stored data, or "contained" blast radius when the change touches code many features share. Otherwise it **agrees**. Leave the line out when there's no Merge Danger section.

### Format

Start your comment with exactly this block, keeping the tier word as written:

```
### Review depth: deep 🔴
**Why:** <one line: the main reason, or the matched categories>
**Look here:** <up to 3 file:line ranges where the risk is; leave this line out for skim>
**Merge Danger check:** <agrees | disagrees: one-line reason>
```

Use `skim 🟢`, `intent 🟡` or `deep 🔴`. A workflow step reads that word and applies the `review:<tier>` label, so don't apply labels yourself.
