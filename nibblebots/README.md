# 🤖 Nibblebots

**Nibblebots** are automated GitHub bots for the Niblit project — similar to
Dependabot, but focused on codebase improvement rather than dependency updates.

They run as **scheduled GitHub Actions** and create Issues with their findings.
**They never commit or push code** — only the owner reviews and merges changes.

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

---

### 2. AIOS Research Bot (`nibblebot-aios-research`)

Researches top AI OS, embedded AI, and hardware-adaptive AI repositories to
gather ideas for building **Niblit AI OS Complete** — an artificial intelligence
operating system that works across different hardware and grows autonomously.

**Schedule:** Every Tuesday at 08:00 UTC.

**What it researches:**
- AI operating systems (autonomous systems, intelligent OS architectures)
- Hardware-adaptive AI (edge AI, TinyML, embedded AI)
- Self-improving systems (autonomous agents, evolving AI)
- Multi-platform AI (cross-platform, portable AI)

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `AIOS_TOPICS` | *(built-in 13 topics)* | Override research topics |
| `AIOS_MAX_REPOS` | `8` | Max repos per topic |
| `AIOS_DRY_RUN` | `false` | Print instead of creating issue |

---

### 3. AIOS Architecture Bot (`nibblebot-aios-architecture`)

Introspects the Niblit codebase and proposes how existing modules map to
AIOS layers (Kernel, HAL, Memory, Intelligence, Learning, Network, App, Security).

**Schedule:** Every Wednesday at 09:00 UTC.

**What it generates:**
- ASCII system architecture diagram
- Module-to-layer mapping table
- Gap analysis (missing components)
- Hardware compatibility matrix
- Growth/improvement pipeline design
- Inter-layer communication proposal

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `AIOS_DRY_RUN` | `false` | Print instead of creating issue |

---

### 4. AIOS Integration Bot (`nibblebot-aios-integration`)

Studies the most successful AI projects on GitHub and proposes how their best
patterns can be integrated into Niblit to make it a complete working AI OS.

**Schedule:** Every Thursday at 10:00 UTC.

**What it does:**
- Researches top LLM frameworks, AI agents, AI OS projects, edge AI tools
- Extracts transferable patterns and architecture ideas
- Cross-references with Niblit's existing capabilities
- Generates a prioritized integration roadmap (quick wins → long-term vision)

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `INTEGRATION_TOPICS` | *(built-in categories)* | Override search topics |
| `INTEGRATION_MAX_REPOS` | `5` | Max repos per category |
| `INTEGRATION_DRY_RUN` | `false` | Print instead of creating issue |

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
│                                 │
│  ⛔ NEVER commits or pushes    │
│     Only owner merges changes   │
└─────────────────────────────────┘
```

Nibblebots have **no external dependencies** — they use only the Python
standard library and the GitHub REST API (via `urllib`). The `GITHUB_TOKEN`
is provided automatically by GitHub Actions.

---

### 5. Deployment Bot (`nibblebot-deployment`)

Monitors failed GitHub Actions workflow runs, diagnoses the root-cause errors,
and opens/updates a GitHub Issue with actionable fix suggestions. Triggers
automatically when any workflow fails, and also runs on a daily schedule.

**Schedule:** Every day at 06:00 UTC (+ triggered on every failed workflow_run).

**What it diagnoses:**
- Python SyntaxError / IndentationError / ImportError
- pip installation failures and missing packages
- Test failures (pytest)
- Authentication / authorization errors (expired secrets)
- Docker build errors
- Network timeouts and connection failures
- Non-zero exit codes with root-cause context

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `DEPLOY_BOT_LOOKBACK` | `48` | Hours to look back for failed runs |
| `DEPLOY_BOT_MAX_RUNS` | `10` | Max failed runs to inspect per execution |
| `DEPLOY_BOT_DRY_RUN` | `false` | Print issue body instead of creating it |

---

### 6. Live Research Bot (`nibblebot-research`)

Enhanced research bot that uses the GitHub REST API to study repositories
**live** — fetching READMEs, recent commits, language breakdowns, and
contributor data. Accumulates a **knowledge layer** from past nibblebot
issues so each run builds on previous discoveries, making Niblit and
Nibblebot progressively more knowledgeable about software patterns.

**Schedule:** Every Friday at 09:00 UTC.

**What it researches:**
- AI agents, LLM frameworks, autonomous agents
- Knowledge graphs, vector databases, RAG systems
- Self-improving and continual-learning systems
- Software architecture and design patterns
- Deployment automation and DevOps

**Knowledge Layer:**
- Reads past nibblebot issues to extract accumulated knowledge
- Skips repos already studied in previous runs
- Identifies **new** patterns not seen before
- Tracks knowledge growth over time

**Configuration:**

| Variable | Default | Description |
|----------|---------|-------------|
| `RESEARCH_TOPICS` | *(built-in 15 topics)* | Override research topics |
| `RESEARCH_MAX_REPOS` | `6` | Max repos per topic |
| `RESEARCH_DEEP_DIVE` | `false` | Fetch language breakdown per repo |
| `RESEARCH_DRY_RUN` | `false` | Print instead of creating issue |

---

## Weekly Schedule

| Day | Bot | Purpose |
|-----|-----|---------|
| Monday 07:00 | Improvement Bot | Code quality & best practices |
| Tuesday 08:00 | AIOS Research | AI OS / hardware / self-improving repos |
| Wednesday 09:00 | AIOS Architecture | Module mapping & system design |
| Thursday 10:00 | AIOS Integration | Integration roadmap from top projects |
| Friday 09:00 | Live Research Bot | GitHub REST API research + knowledge layer |
| Daily 06:00 | Deployment Bot | Monitor & diagnose failed CI/CD builds |

---

## Adding a New Nibblebot

1. Create a script in `nibblebots/` (e.g. `nibblebots/my_bot.py`)
2. Create a workflow in `.github/workflows/nibblebot-my-bot.yml`
3. Use the `nibblebot` or `nibblebot-aios` label for issues
4. Follow the pattern: study → compare → report via Issue
5. **Never commit or push** — only create/update Issues

---

## Labels

- **`nibblebot`** (purple `#7057ff`) — general improvement suggestions
- **`nibblebot-aios`** (blue `#0075ca`) — AIOS research, architecture, and integration proposals
- **`nibblebot-deploy`** (red `#d73a4a`) — deployment failure diagnosis reports
- **`nibblebot-research`** (green `#0e8a16`) — live GitHub research + knowledge layer reports
