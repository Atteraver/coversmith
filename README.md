# CoverSmith

Autonomous Java test coverage agent built on the RuleSmith agent framework.

**Goal:** given a GitHub pull request, achieve 100% line + branch + mutation coverage on the changed lines — using the fewest tests possible.

---

## How it works

CoverSmith runs a free ReAct loop (no fixed pipeline). Given a PR number, it:

1. Fetches the PR diff to find which source files changed
2. Pulls open SonarQube issues for the PR
3. Fetches exact uncovered/partially-covered line numbers per file from SonarQube
4. Reads source + test files to understand existing coverage
5. Writes minimal JUnit 5 tests targeting exactly the uncovered lines and branches — **requires your approval**
6. Runs Maven + JaCoCo to verify the tests pass
7. Runs PIT mutation coverage — **requires your approval** (slow: 1-5 min per class)
8. Revises tests if mutants survive (up to 3 attempts)
9. Cleans up temporary context files

Two approval gates keep you in control: writing test files, and running mutation coverage.

### Persistent context files

Because the agent uses a sliding window memory, long runs may evict earlier results. CoverSmith solves this by writing two temp files in the directory where you run it:

| File | Contents |
|------|----------|
| `.coversmith_issues.json` | SonarQube issues for the PR |
| `.coversmith_uncovered.json` | Uncovered lines per file |

These are updated by the agent and deleted by `cleanup_context()` at the end.

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-org/coversmith.git ~/tools/coversmith
cd ~/tools/coversmith
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```
HAI_BASE_URL=https://your-hai-proxy/v1
HAI_API_KEY=your-key
HAI_MODEL=claude-sonnet-4-6

# Optional — only needed if SonarQube requires token auth beyond browser session
SONAR_TOKEN=your-sonar-token
SONAR_BASE_URL=https://sonar.tools.sap
```

Load them before running:

```bash
set -a && source .env && set +a
```

---

## Running from any repo

You don't need to clone CoverSmith into your repo. Run it from anywhere — the temp context files land in your **current working directory**, so cd into your repo first:

```bash
# From your target repo
cd /path/to/x-iep-service

# Run CoverSmith
python3 ~/tools/coversmith/agent.py \
  MyOrg/x-iep-service \       # GitHub owner/repo
  42 \                         # PR number
  CALMRun-x-iep-service \      # SonarQube component key
  srv                          # Maven submodule root (relative or absolute)
```

Or with an absolute Maven path:

```bash
python3 ~/tools/coversmith/agent.py \
  MyOrg/x-iep-service 42 CALMRun-x-iep-service \
  /path/to/x-iep-service/srv
```

### Shorthand alias (add to `~/.zshrc`)

```bash
alias coversmith='python3 ~/tools/coversmith/agent.py'
```

Then from any repo:

```bash
cd /path/to/x-iep-service
coversmith MyOrg/x-iep-service 42 CALMRun-x-iep-service srv
```

---

## Tools registered

| Tool | Approval | Purpose |
|------|----------|---------|
| `fetch_pr_diff` | No | Gets diff + changed file list from GitHub |
| `fetch_sonar_issues` | No | Pulls open issues from SonarQube, writes `.coversmith_issues.json` |
| `fetch_uncovered_lines` | No | Gets exact uncovered lines per file, writes `.coversmith_uncovered.json` |
| `read_uncovered_context` | No | Re-reads `.coversmith_uncovered.json` after window eviction |
| `read_issues_context` | No | Re-reads `.coversmith_issues.json` after window eviction |
| `read_source_file` | No | Reads any Java source or test file |
| `write_test_file` | **Yes** | Writes or overwrites a test file |
| `run_tests` | No | Runs Maven + JaCoCo for a specific test class |
| `run_mutation_coverage` | **Yes** | Runs PIT mutation coverage (slow) |
| `cleanup_context` | No | Deletes both temp context files |

---

## Project structure

```
coversmith/
├── agent.py          ← entry point; system prompt + Agent wiring
├── tools.py          ← all 10 tools registered on a ToolRegistry instance
├── framework/        ← copied from RuleSmith (Agent, ToolRegistry, LLMClient, Memory, Tracer)
├── reports/          ← per-run markdown reports (gitignored)
├── .env.example
└── requirements.txt
```

---

## Environment variables reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HAI_BASE_URL` | Yes | — | LLM proxy base URL |
| `HAI_API_KEY` | Yes | — | API key |
| `HAI_MODEL` | No | `claude-sonnet-4-6` | Model name |
| `SONAR_TOKEN` | No | — | SonarQube token (Basic auth) |
| `SONAR_BASE_URL` | No | `https://sonar.tools.sap` | SonarQube host |
