# CoverSmith

Autonomous Java test coverage agent built on the RuleSmith agent framework.

**Goal:** given a GitHub pull request, achieve 100% line + branch + mutation coverage on the changed lines — using the fewest tests possible.

---

## How it works

CoverSmith runs a free ReAct loop (no fixed pipeline). Given a PR URL, it:

1. **Verifies SonarQube connection** — checks reachability, auth, and component key before doing anything else. Stops and reports clearly if anything is wrong.
2. Fetches the PR diff to find which source files changed
3. Pulls open SonarQube issues for the PR
4. Fetches exact uncovered/partially-covered line numbers per file from SonarQube
5. Reads source + test files to understand existing coverage
6. Writes minimal JUnit 5 tests targeting exactly the uncovered lines and branches — **requires your approval**
7. Runs Maven + JaCoCo to verify the tests pass
8. Runs PIT mutation coverage — **requires your approval** (slow: 1-5 min per class)
9. Revises tests if mutants survive (up to 3 attempts)
10. Cleans up temporary context files

Two approval gates keep you in control: writing test files, and running mutation coverage.

### Persistent context files

Because the agent uses a sliding window memory, long runs may evict earlier results. CoverSmith writes two temp files in your working directory so context survives:

| File | Contents |
|------|----------|
| `.coversmith_issues.json` | SonarQube issues for the PR |
| `.coversmith_uncovered.json` | Uncovered lines per file |

Both are deleted by `cleanup_context()` at the end of each run.

---

## Setup (one time)

### 1. Clone and create venv

```bash
git clone .../coversmith ~/tools/coversmith
cd ~/tools/coversmith
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp ~/tools/coversmith/.env.example ~/tools/coversmith/.env
```

Open `.env` and fill in the two required values:

```
HAI_BASE_URL=https://your-hai-proxy/v1
HAI_API_KEY=your-key
```

`.env` is loaded automatically on every run — no `source` or `export` needed.

### 3. Get your SonarQube token

CoverSmith calls the SonarQube API directly (not via browser). It needs a personal access token:

1. Open [https://sonar.tools.sap/account/security](https://sonar.tools.sap/account/security) in your browser
2. Under **Generate Tokens**, enter a name (e.g. `coversmith`) and click **Generate**
3. Copy the token — you only see it once
4. Add it to your `.env`:
   ```
   SONAR_TOKEN=your-token-here
   ```

> **Why a token?** The SonarQube UI uses browser session cookies. CoverSmith makes direct API calls (`/api/issues/search`, `/api/sources/lines`) which require token-based Basic auth. Without a token, all Sonar calls return HTTP 401.

### 4. Add to PATH

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

**Minimal — from any directory:**

```bash
coversmith https://github.tools.sap/MyOrg/x-iep-service/pull/42 CALMRun-x-iep-service
```

**With explicit Maven root** (when tests live in a submodule like `srv/`):

```bash
coversmith https://github.tools.sap/MyOrg/x-iep-service/pull/42 CALMRun-x-iep-service /path/to/x-iep-service/srv
```

If `maven_project_root` is omitted, it defaults to the current working directory.

### Finding your SonarQube component key

The component key is shown on your project's SonarQube dashboard URL:
```
https://sonar.tools.sap/dashboard?id=CALMRun-x-iep-service
                                      ^^^^^^^^^^^^^^^^^^^^^ this is the key
```

Or browse [https://sonar.tools.sap/projects](https://sonar.tools.sap/projects) and look at each project's URL.

---

## Tools registered

| Tool | Approval | Purpose |
|------|----------|---------|
| `verify_sonar_connection` | No | Checks reachability, auth, and component key — **runs first, stops on failure** |
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

## Troubleshooting SonarQube

| Symptom | Cause | Fix |
|---------|-------|-----|
| `HTTP 401` on all Sonar calls | No token or token expired | Generate new token at `sonar.tools.sap/account/security`, add to `.env` as `SONAR_TOKEN` |
| `Cannot reach SonarQube` | Network / VPN | Ensure VPN is connected; verify `SONAR_BASE_URL` in `.env` |
| `Component not found` | Wrong component key | Check the key in the SonarQube project URL |
| `verify_sonar_connection` passes but issues are empty | PR not analysed yet | Wait for the SonarQube PR scan to complete (triggered by CI) |

The `verify_sonar_connection` tool runs a 3-step pre-flight check (server reachable → auth valid → component exists) and prints an exact fix hint for each failure type.

---

## Project structure

```
coversmith/
├── coversmith         ← bash wrapper (add to PATH); re-execs under .venv Python
├── _coversmith.py     ← main entry point: env checks, arg parse, agent run, report
├── agent.py           ← system prompt + Agent wiring + URL parser + .env loader
├── tools.py           ← all 11 tools on a ToolRegistry instance
├── framework/         ← copied from RuleSmith (unchanged)
├── reports/           ← per-run markdown reports (gitignored)
├── .env               ← your credentials (gitignored)
├── .env.example       ← template
└── requirements.txt
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HAI_BASE_URL` | Yes | — | LLM proxy base URL |
| `HAI_API_KEY` | Yes | — | API key |
| `HAI_MODEL` | No | `claude-sonnet-4-6` | Model name |
| `SONAR_TOKEN` | **Yes** | — | SonarQube personal access token |
| `SONAR_BASE_URL` | No | `https://sonar.tools.sap` | SonarQube host |

All values are read from `~/tools/coversmith/.env` automatically. Shell environment variables already exported take precedence and are not overwritten.
