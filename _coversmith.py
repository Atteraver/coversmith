"""
CoverSmith main entry point — called by the `coversmith` shell wrapper.
Handles: .env loading, pre-flight checks, arg parsing, agent run, report writing.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the coversmith package dir is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import _load_env, _parse_pr_url, build_agent

# ── 1. Load .env ──────────────────────────────────────────────────────────────
_load_env()

# ── 2. Pre-flight: check required env vars before touching the LLM ────────────
_REQUIRED = ["HAI_BASE_URL", "HAI_API_KEY"]
_missing = [k for k in _REQUIRED if not os.getenv(k)]

if _missing:
    env_path = Path(__file__).parent / ".env"
    print("─" * 55)
    print("  CoverSmith: missing required environment variables")
    print("─" * 55)
    for k in _missing:
        print(f"  ✗ {k}")
    print()
    if not env_path.exists():
        print(f"  No .env file found at: {env_path}")
        print()
        print("  Quick setup:")
        print(f"    cp {env_path.parent}/.env.example {env_path}")
        print(f"    # then edit {env_path} and fill in your values")
    else:
        print(f"  .env exists at {env_path} but is missing the above keys.")
        print("  Add them and re-run.")
    print("─" * 55)
    sys.exit(1)

# ── 3. Parse args ─────────────────────────────────────────────────────────────
if len(sys.argv) < 3:
    print("Usage: coversmith <pr_url> <sonar_component_key> [maven_project_root]")
    print()
    print("Examples:")
    print("  coversmith https://github.tools.sap/MyOrg/x-iep-service/pull/42 CALMRun-x-iep-service")
    print("  coversmith https://github.tools.sap/MyOrg/x-iep-service/pull/42 CALMRun-x-iep-service /path/to/clone/srv")
    sys.exit(1)

pr_url = sys.argv[1]
sonar_key = sys.argv[2]
repo_path = sys.argv[3] if len(sys.argv) > 3 else os.getcwd()

try:
    repo, pr_number = _parse_pr_url(pr_url)
except ValueError as e:
    print(f"Error: {e}")
    sys.exit(1)

# ── 4. Run agent ──────────────────────────────────────────────────────────────
print(f"\nCoverSmith starting")
print(f"  PR:      {pr_url}")
print(f"  Repo:    {repo}  PR #{pr_number}")
print(f"  Sonar:   {sonar_key}")
print(f"  Maven:   {repo_path}")
print()

agent = build_agent()

goal = (
    f"Achieve 100% line, branch, and mutation coverage on the new/changed lines "
    f"in PR #{pr_number} of {repo}. "
    f"SonarQube component key: {sonar_key}. "
    f"Maven project root (for running tests): {repo_path}. "
    f"Start by calling verify_sonar_connection('{sonar_key}'). "
    f"Work through all changed source files. "
    f"Call cleanup_context() when done."
)

result = agent.run(goal=goal)

# ── 5. Print output ───────────────────────────────────────────────────────────
print("\n")
print("=" * 60)
print("  COVERSMITH REPORT")
print("=" * 60)
print()
print(result.output)
print()
result.trace.print_summary()

# ── 6. Save report ────────────────────────────────────────────────────────────
reports_dir = Path(__file__).parent / "reports"
reports_dir.mkdir(exist_ok=True)
ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
report_path = reports_dir / f"report_pr{pr_number}_{ts}.md"

with open(report_path, "w") as f:
    f.write(f"# CoverSmith — PR #{pr_number} Coverage Run\n\n")
    f.write(f"**Repo:** {repo}  \n")
    f.write(f"**PR URL:** {pr_url}  \n")
    f.write(f"**SonarQube key:** {sonar_key}  \n")
    f.write(f"**Maven root:** {repo_path}  \n")
    f.write(f"**Run time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  \n\n")
    f.write("---\n\n## Agent Output\n\n")
    f.write(result.output)
    f.write("\n\n---\n\n## Execution Trace (JSON)\n\n```json\n")
    f.write(result.trace.to_json())
    f.write("\n```\n")

print(f"\nReport saved: {report_path}\n")
