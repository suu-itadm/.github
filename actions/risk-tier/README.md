# Risk tier

Labels each PR `review:skim`, `review:intent` or `review:deep` so reviewers know how closely to read it and where to look. It adds a "Review depth" block to the Claude Code Summary comment. See https://github.com/suu-itadm/.github/issues/5.

There are two parts:

1. **Rules.** Each repo's `.github/risk-tiers.yml` lists the files and code it treats as sensitive. If a PR matches any rule, it's `review:deep`, and Claude can't lower that.
2. **Claude.** For every other PR, the Claude Code Summary picks the tier, says why, and points at the lines to read.

Labels are advisory. Nothing blocks a merge. When a label is wrong, add `tier-miss` to the PR so we can measure accuracy.

## Use it in a repo

In the repo's `claude-code-review.yml`, make sure the job has these permissions:

```yaml
    permissions:
      contents: read
      pull-requests: write   # labels
      issues: write          # create the labels
      id-token: write
```

Then add one step before the Claude step and one after it:

```yaml
      - name: Checkout repository
        uses: actions/checkout@v6

      - name: Risk tier
        id: risk
        uses: suu-itadm/.github/actions/risk-tier@main
        with:
          pr: ${{ github.event.pull_request.number }}

      - name: Run Claude Code Summary
        uses: anthropics/claude-code-action@v1
        with:
          prompt: |
            ...the repo's existing prompt...

            ${{ steps.risk.outputs.prompt }}

      - name: Review depth label
        uses: suu-itadm/.github/actions/risk-tier/label@main
        with:
          pr: ${{ github.event.pull_request.number }}
          deep: ${{ steps.risk.outputs.deep }}
```

Claude doesn't need any extra tools. It writes the tier into its comment, and the label step reads it from there.

## Rules file

`.github/risk-tiers.yml`:

```yaml
# Files matching these are skipped entirely: no rule applies to them.
ignore:
  - "**/tests/**"

categories:
  schema:
    paths: ["**/migrations/**"]
  raw-sql:
    lines: [".raw(", "cursor("]
```

- `paths` are globs. `**` matches any number of directories, and `*` stays within one.
- `lines` are plain substrings, not regexes. They're matched against the lines a PR adds or removes, not the surrounding context.
- Only these categories are allowed, so every repo shares one vocabulary. Leave out any a repo doesn't have:

| Category | Means |
|---|---|
| `schema` | migrations, DDL, table or column changes |
| `auth` | login, permissions, who can see or do what |
| `system-of-record` | writes to Banner or another external system |
| `money` | payments, pcard, transfers, budgets, deposits |
| `student-records` | FERPA-protected data |
| `raw-sql` | hand-written SQL or cursors |
| `unsafe-output` | unescaped HTML, `dangerouslySetInnerHTML`, `mark_safe` |
| `secrets-config` | settings, env, keys, CORS, cookies |
| `ci-deploy` | workflows, Kamal, Docker, deploy scripts |
| `scheduled` | cron, Celery tasks, nightly jobs |

A repo with no rules file still works: Claude picks every tier.

If GitHub can't return the diff (it refuses diffs over 20,000 lines), the PR is labeled deep.

If `risk-tiers.yml` is invalid (bad YAML, an unknown category, or the wrong shape), the step posts a warning and the PR is labeled deep. The Claude review still runs.

## Tests

```
cd actions/risk-tier && python3 -m unittest -v
```
