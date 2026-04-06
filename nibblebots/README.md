# 🤖 Nibblebots

**Nibblebots** are automated GitHub bots for the Niblit project — similar to
Dependabot, but focused on codebase improvement rather than dependency updates.

They run as **scheduled GitHub Actions** and create Issues with their findings.

---

## Available Nibblebots

### 1. Improvement Bot (`nibblebot-improve`)

Studies top-starred GitHub repos for configurable topics, compares their
patterns and best practices with the Niblit codebase, and opens a GitHub
Issue listing actionable improvement suggestions.

**Schedule:** Every Monday at 07:00 UTC (configurable in the workflow).

**What it checks:**
- Test coverage ratio vs. reference repos
- Missing community files (CONTRIBUTING.md, CHANGELOG.md, etc.)
- Code quality patterns (type hints, pre-commit hooks, pyproject.toml)
- Architecture patterns from highly-starred repos
- File size / complexity heuristics

**Configuration** (workflow environment variables):

| Variable | Default | Description |
|----------|---------|-------------|
| `NIBBLEBOT_TOPICS` | `ai-agent,llm-framework` | Comma-separated GitHub topics to study |
| `NIBBLEBOT_MAX_REPOS` | `5` | Max reference repos per topic |
| `NIBBLEBOT_DRY_RUN` | `false` | Print issue body instead of creating it |

**Manual trigger:**
Go to **Actions → 🤖 Nibblebot: Improvement Scanner → Run workflow** and
optionally override topics or enable dry-run mode.

---

## How Nibblebots Work

```
┌─────────────────────────────────┐
│  GitHub Actions (scheduled)     │
│  .github/workflows/nibblebot-*  │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  nibblebots/*.py                │
│  (standalone Python scripts)    │
│                                 │
│  1. Study reference repos       │
│     (GitHub REST API)           │
│                                 │
│  2. Introspect own codebase     │
│     (local filesystem scan)     │
│                                 │
│  3. Compare & generate          │
│     suggestions                 │
│                                 │
│  4. Open/update GitHub Issue    │
│     with findings               │
└─────────────────────────────────┘
```

Nibblebots have **no external dependencies** — they use only the Python
standard library and the GitHub REST API (via `urllib`). The `GITHUB_TOKEN`
is provided automatically by GitHub Actions.

---

## Adding a New Nibblebot

1. Create a script in `nibblebots/` (e.g. `nibblebots/my_bot.py`)
2. Create a workflow in `.github/workflows/nibblebot-my-bot.yml`
3. Use the `nibblebot` label for issues so they're grouped together
4. Follow the pattern: study → compare → report via Issue

---

## Labels

Nibblebots automatically create and use the **`nibblebot`** label
(purple `#7057ff`) for all issues they manage.
