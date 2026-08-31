import os
import sys
from datetime import datetime, timezone

from framework import Agent, ExecutionTrace
from framework.llm import LLMClient
from framework.memory import SlidingWindowMemory
from tools import registry

SYSTEM_PROMPT = """You are CoverSmith — an autonomous test coverage agent for Java/Maven projects.

Your goal is to achieve 100% line coverage, 100% branch coverage, and 100% mutation coverage
on the lines changed in a pull request, using the fewest tests possible.

## Scope rule
Only add or modify tests for lines that appear in the PR diff. Do not touch untouched code.

## Investigation strategy
1. Fetch the PR diff to find which source files changed.
2. Fetch SonarQube issues to understand open quality problems.
3. For each changed source file, fetch its uncovered lines from SonarQube.
4. Read the source file and its existing test file to understand what is already covered.
5. Plan the minimal set of tests that cover every uncovered line and every branch.
   - One @ParameterizedTest when multiple inputs exercise the same branches.
   - One @Test per genuinely distinct scenario.
   - Modify existing tests before adding new ones.
6. Write the test file (requires approval).
7. Run the tests to confirm they pass.
8. Run mutation coverage (requires approval — slow, ~1-5 min per class).
9. If mutants survive or lines remain uncovered, revise and re-run. Max 3 attempts.
10. Call cleanup_context() as the very last step.

## Context files
Two temporary files persist context across the sliding window:
  .coversmith_issues.json    — SonarQube issues
  .coversmith_uncovered.json — uncovered lines per file
If you suspect results were evicted from memory, call read_uncovered_context()
or read_issues_context() to reload them.

## Test conventions
- JUnit 5 + Mockito.
- Class name: <SourceClass>Test.java in the same package under src/test/java.
- Method name: test<Method>_<Scenario>.
- Assert exact return values; verify mock interactions for void methods.
- No // Given/When/Then comments. No PR references in test code.

## Completion
When all uncovered lines are covered and mutation score is 100%, report:
  - Line % (new code)
  - Branch % (new code)
  - Mutation %
  - Files modified
Then call cleanup_context() and stop."""


def build_agent() -> Agent:
    return Agent(
        name="CoverSmith",
        system_prompt=SYSTEM_PROMPT,
        registry=registry,
        llm=LLMClient(
            model=os.getenv("HAI_MODEL", "claude-sonnet-4-6"),
            base_url=os.getenv("HAI_BASE_URL"),
            api_key=os.getenv("HAI_API_KEY"),
        ),
        memory=SlidingWindowMemory(max_messages=30),
        tracer=ExecutionTrace(),
        max_iterations=20,
    )


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python agent.py <owner/repo> <pr_number> <sonar_component_key> [repo_path]")
        print()
        print("Examples:")
        print("  python agent.py MyOrg/my-service 42 MyOrg-my-service")
        print("  python agent.py MyOrg/my-service 42 MyOrg-my-service /path/to/local/clone/srv")
        sys.exit(1)

    repo = sys.argv[1]
    pr_number = int(sys.argv[2])
    sonar_key = sys.argv[3]
    repo_path = sys.argv[4] if len(sys.argv) > 4 else os.getcwd()

    agent = build_agent()

    goal = (
        f"Achieve 100% line, branch, and mutation coverage on the new/changed lines "
        f"in PR #{pr_number} of {repo}. "
        f"SonarQube component key: {sonar_key}. "
        f"Maven project root (for running tests): {repo_path}. "
        f"Work through all changed source files. "
        f"Call cleanup_context() when done."
    )

    result = agent.run(goal=goal)

    print("\n")
    print("=" * 60)
    print("  COVERSMITH REPORT")
    print("=" * 60)
    print()
    print(result.output)
    print()
    result.trace.print_summary()

    # Write run report
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(reports_dir, f"report_pr{pr_number}_{ts}.md")

    with open(report_path, "w") as f:
        f.write(f"# CoverSmith — PR #{pr_number} Coverage Run\n\n")
        f.write(f"**Repo:** {repo}  \n")
        f.write(f"**SonarQube key:** {sonar_key}  \n")
        f.write(f"**Run time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  \n\n")
        f.write("---\n\n")
        f.write("## Agent Output\n\n")
        f.write(result.output)
        f.write("\n\n---\n\n")
        f.write("## Execution Trace (JSON)\n\n")
        f.write("```json\n")
        f.write(result.trace.to_json())
        f.write("\n```\n")

    print(f"\nReport saved: {report_path}\n")
