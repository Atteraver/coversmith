# CoverSmith

Autonomous Java test coverage agent built on the RuleSmith agent framework.

**Goal:** given a GitHub pull request, achieve 100% line + branch + mutation coverage on the changed lines — using the fewest tests possible.

---

## How it works

CoverSmith runs a free ReAct loop (no fixed pipeline). Given a PR URL, it:

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

Because the agent uses a sliding window memory, long runs may evict earlier results. CoverSmith solves this by writing two temp files in your working directory:

| File | Contents |
|------|----------|
| `.coversmith_issues.json` | SonarQube issues for the PR |
| `.coversmith_uncovered.json` | Uncovered lines per file |

These are updated by the agent and deleted by `cleanup_context()` at the end.

---

## Setup (one time)

### 1. Clone and install

```bash
git clone .../coversmith ~/tools/coversmith
cd ~/tools/coversmith
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp ~/tools/coversmith/.env.example ~/tools/coversmith/.env
# edit .env — fill in HAI_BASE_URL and HAI_API_KEY
```

`.env` is loaded automatically every run — no `source` or `export` needed.

### 3. Add to PATH

Add to `~/.zshrc`:

```bash
export PATH="$HOME/tools/coversmith:$PATH"
```

Then reload: `source ~/.zshrc`

---

## Usage

```
coversmith <pr_url> <sonar_component_key> [maven_project_root]
```

**From any directory:**

```bash
coversmith https://github.tools.sap/MyOrg/x-iep-service/pull/42 CALMRun-x-iep-service
```

**With an explicit Maven root** (when tests live in a submodule like `srv/`):

```bash
coversmith https://github.tools.sap/MyOrg/x-iep-service/pull/42 CALMRun-x-iep-service /path/to/x-iep-service/srv
```

If `maven_project_root` is omitted, it defaults to the current working directory.

The PR URL is parsed automatically — no need to split repo and PR number manually.

---

## Tools registered

| Tool | Approval | Purpose |
|------|----------|---------|
| `fetch_pr_diff` | No | Gets diff + changed file list from GitHub |
| `fetch_sonar_issues` | No | Pulls open issues from SonarQube → `.coversmith_issues.json` |
| `fetch_uncovered_lines` | No | Gets exact uncovered lines per file → `.coversmith_uncovered.json` |
| `read_uncovered_context` | No | Re-reads uncovered lines file if evicted from memory |
| `read_issues_context` | No | Re-reads issues file if evicted from memory |
| `read_source_file` | No | Reads any Java source or test file |
| `write_test_file` | **Yes** | Writes or overwrites a test file |
| `run_tests` | No | Runs Maven + JaCoCo for a specific test class |
| `run_mutation_coverage` | **Yes** | Runs PIT mutation coverage (slow) |
| `cleanup_context` | No | Deletes both temp context files |

---

## Project structure

```
coversmith/
├── coversmith        ← executable entry point (add to PATH)
├── agent.py          ← system prompt + Agent wiring + URL parser + .env loader
├── tools.py          ← all 10 tools on a ToolRegistry instance
├── framework/        ← copied from RuleSmith (unchanged)
├── reports/          ← per-run markdown reports (gitignored)
├── .env              ← your credentials (gitignored)
├── .env.example      ← template
└── requirements.txt
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HAI_BASE_URL` | Yes | — | LLM proxy base URL |
| `HAI_API_KEY` | Yes | — | API key |
| `HAI_MODEL` | No | `claude-sonnet-4-6` | Model name |
| `SONAR_TOKEN` | No | — | SonarQube token (if Basic auth required) |
| `SONAR_BASE_URL` | No | `https://sonar.tools.sap` | SonarQube host |

All values are read from `~/tools/coversmith/.env` automatically. Shell environment variables take precedence (existing `HAI_*` exports are not overwritten).
