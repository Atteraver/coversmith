"""
CoverSmith tools — each tool maps to one step of the coverage investigation.

Temp files used as persistent context (survive sliding window eviction):
  .coversmith_issues.json     — SonarQube issues for the PR
  .coversmith_uncovered.json  — uncovered/partially-covered lines per file

Both files are written/updated by tools and deleted by cleanup_context().
"""

import json
import os
import subprocess
import sys

from framework import ToolRegistry

registry = ToolRegistry()

# ── Temp context files (relative to cwd of the calling repo) ─────────────────
_ISSUES_FILE = ".coversmith_issues.json"
_UNCOVERED_FILE = ".coversmith_uncovered.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_json_file(path: str) -> dict | list:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _write_json_file(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _run(cmd: str, cwd: str = None) -> tuple[int, str, str]:
    """Run a shell command, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ── Shared Sonar HTTP helper ──────────────────────────────────────────────────

def _sonar_request(url: str) -> tuple[int, dict | None, str]:
    """
    Make a GET request to SonarQube.
    Returns (http_status, parsed_json_or_None, error_message).
    Auth: prefers SONAR_TOKEN (Basic); falls back to unauthenticated.
    """
    import urllib.request
    import urllib.error
    import base64

    token = os.getenv("SONAR_TOKEN", "")
    req = urllib.request.Request(url)
    if token:
        creds = base64.b64encode(f"{token}:".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read()), ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:300]
        except Exception:
            body = ""
        return e.code, None, f"HTTP {e.code} {e.reason}: {body}"
    except Exception as e:
        return 0, None, str(e)


# ── Tools ─────────────────────────────────────────────────────────────────────

@registry.tool(
    description=(
        "Verify that SonarQube is reachable and authenticated. "
        "Pass sonar_component_key (e.g. 'CALMRun-x-iep-service'). "
        "MUST be called before any other SonarQube tool. "
        "Returns connection status, auth method used, and server version. "
        "If this fails, stop and report the exact error to the user — do not proceed."
    )
)
def verify_sonar_connection(sonar_component_key: str) -> dict:
    sonar_base = os.getenv("SONAR_BASE_URL", "https://sonar.tools.sap")
    token = os.getenv("SONAR_TOKEN", "")
    auth_method = "token (SONAR_TOKEN)" if token else "unauthenticated"

    # 1. Check server is reachable via /api/system/status
    status_url = f"{sonar_base}/api/system/status"
    code, data, err = _sonar_request(status_url)
    if code == 0 or data is None:
        return {
            "connected": False,
            "error": f"Cannot reach SonarQube at {sonar_base}: {err}",
            "fix": (
                "Check that SONAR_BASE_URL is correct and the server is reachable. "
                "If on VPN-gated network, ensure VPN is connected."
            ),
        }

    server_version = data.get("version", "unknown")
    server_status = data.get("status", "unknown")

    # 2. Check auth by hitting a lightweight authenticated endpoint
    auth_url = f"{sonar_base}/api/authentication/validate"
    auth_code, auth_data, auth_err = _sonar_request(auth_url)
    auth_valid = auth_data.get("valid", False) if auth_data else False

    if not auth_valid:
        hint = (
            "Set SONAR_TOKEN in your .env file. "
            "Generate a token at: "
            f"{sonar_base}/account/security"
        )
        return {
            "connected": True,
            "authenticated": False,
            "server_version": server_version,
            "server_status": server_status,
            "auth_method": auth_method,
            "error": f"Authentication failed ({auth_code}): {auth_err or 'token invalid or missing'}",
            "fix": hint,
        }

    # 3. Verify component key exists
    component_url = (
        f"{sonar_base}/api/components/show"
        f"?component={sonar_component_key}"
    )
    comp_code, comp_data, comp_err = _sonar_request(component_url)

    if comp_code != 200 or comp_data is None:
        return {
            "connected": True,
            "authenticated": True,
            "server_version": server_version,
            "component_found": False,
            "error": f"Component '{sonar_component_key}' not found ({comp_code}): {comp_err}",
            "fix": (
                f"Double-check the sonar_component_key. "
                f"Browse {sonar_base}/projects to find the correct key."
            ),
        }

    component_name = comp_data.get("component", {}).get("name", sonar_component_key)

    return {
        "connected": True,
        "authenticated": True,
        "auth_method": auth_method,
        "server_version": server_version,
        "server_status": server_status,
        "component_found": True,
        "component_name": component_name,
        "component_key": sonar_component_key,
        "sonar_base_url": sonar_base,
        "message": "SonarQube connection verified. Ready to fetch issues and coverage data.",
    }


@registry.tool(
    description=(
        "Fetch the diff and file list for a GitHub pull request. "
        "Pass repo as 'owner/repo' and pr_number as an integer. "
        "Returns changed Java source files (excluding test files) and the raw diff."
    )
)
def fetch_pr_diff(repo: str, pr_number: int) -> dict:
    rc_diff, diff, err_diff = _run(
        f"/opt/homebrew/bin/gh pr diff {pr_number} --repo {repo}"
    )
    rc_meta, meta_json, err_meta = _run(
        f"/opt/homebrew/bin/gh pr view {pr_number} --repo {repo} "
        f"--json files,title,headRefName,baseRefName,additions,deletions"
    )

    if rc_meta != 0:
        return {"error": f"Could not fetch PR metadata: {err_meta}"}

    meta = json.loads(meta_json)
    changed_files = [
        f["path"] for f in meta.get("files", [])
        if f["path"].endswith(".java") and "Test" not in f["path"]
    ]
    test_files = [
        f["path"] for f in meta.get("files", [])
        if f["path"].endswith(".java") and "Test" in f["path"]
    ]

    return {
        "title": meta.get("title"),
        "head": meta.get("headRefName"),
        "base": meta.get("baseRefName"),
        "additions": meta.get("additions"),
        "deletions": meta.get("deletions"),
        "changed_source_files": changed_files,
        "changed_test_files": test_files,
        "diff": diff[:8000] if diff else "(diff unavailable)",
    }


@registry.tool(
    description=(
        "Fetch open SonarQube issues for a pull request and save them to the "
        "persistent issues context file. "
        "Pass sonar_component_key (e.g. 'CALMRun-x-iep-service') and pr_number. "
        "Returns a summary and writes .coversmith_issues.json."
    )
)
def fetch_sonar_issues(sonar_component_key: str, pr_number: int) -> dict:
    sonar_base = os.getenv("SONAR_BASE_URL", "https://sonar.tools.sap")

    url = (
        f"{sonar_base}/api/issues/search"
        f"?pullRequest={pr_number}"
        f"&componentKeys={sonar_component_key}"
        f"&issueStatuses=OPEN,CONFIRMED&ps=100"
    )

    code, data, err = _sonar_request(url)
    if data is None:
        return {"error": f"SonarQube issues fetch failed: {err}"}

    issues = data.get("issues", [])
    summarised = [
        {
            "key": i.get("key"),
            "rule": i.get("rule"),
            "severity": i.get("severity"),
            "message": i.get("message"),
            "component": i.get("component"),
            "line": i.get("line"),
            "type": i.get("type"),
        }
        for i in issues
    ]

    _write_json_file(_ISSUES_FILE, {"pr": pr_number, "issues": summarised})

    by_type: dict[str, int] = {}
    for i in summarised:
        t = i.get("type", "UNKNOWN")
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "total_issues": len(summarised),
        "by_type": by_type,
        "issues_file": _ISSUES_FILE,
        "sample": summarised[:10],
    }


@registry.tool(
    description=(
        "Fetch uncovered and partially-covered lines for a specific file in a PR "
        "from SonarQube. Updates the persistent uncovered-lines context file. "
        "Pass sonar_component_key, pr_number, file_component_key "
        "(e.g. 'CALMRun-x-iep-service:srv/src/main/java/com/example/Foo.java'), "
        "from_line and to_line (integers from the PR diff)."
    )
)
def fetch_uncovered_lines(
    sonar_component_key: str,
    pr_number: int,
    file_component_key: str,
    from_line: int,
    to_line: int,
) -> dict:
    sonar_base = os.getenv("SONAR_BASE_URL", "https://sonar.tools.sap")

    url = (
        f"{sonar_base}/api/sources/lines"
        f"?key={file_component_key}"
        f"&pullRequest={pr_number}"
        f"&from={from_line}&to={to_line}"
    )

    code, data, err = _sonar_request(url)
    if data is None:
        return {"error": f"SonarQube sources fetch failed: {err}"}

    lines = data.get("sources", data.get("lines", []))
    uncovered = [
        {"line": l.get("line"), "status": l.get("coverageStatus")}
        for l in lines
        if l.get("coverageStatus") in ("uncovered", "partially-covered")
    ]

    existing = _read_json_file(_UNCOVERED_FILE)
    if not isinstance(existing, dict):
        existing = {}
    existing[file_component_key] = {
        "from_line": from_line,
        "to_line": to_line,
        "uncovered_lines": uncovered,
    }
    _write_json_file(_UNCOVERED_FILE, existing)

    return {
        "file": file_component_key,
        "uncovered_count": len(uncovered),
        "uncovered_lines": uncovered,
        "context_file": _UNCOVERED_FILE,
    }


@registry.tool(
    description=(
        "Read the current uncovered-lines context file. "
        "Returns all files and their uncovered line numbers collected so far. "
        "Use this after the sliding window may have dropped earlier fetch_uncovered_lines results."
    )
)
def read_uncovered_context() -> dict:
    data = _read_json_file(_UNCOVERED_FILE)
    if not data:
        return {"message": "No uncovered context file found. Run fetch_uncovered_lines first."}
    return data


@registry.tool(
    description=(
        "Read the current SonarQube issues context file. "
        "Returns all open issues collected so far. "
        "Use this after the sliding window may have dropped earlier fetch_sonar_issues results."
    )
)
def read_issues_context() -> dict:
    data = _read_json_file(_ISSUES_FILE)
    if not data:
        return {"message": "No issues context file found. Run fetch_sonar_issues first."}
    return data


@registry.tool(
    description=(
        "Read the full content of a source or test Java file. "
        "Pass the absolute or repo-relative file_path. "
        "Use this to understand the code before writing tests."
    )
)
def read_source_file(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    with open(file_path) as f:
        content = f.read()
    lines = content.splitlines()
    return {
        "file": file_path,
        "lines": len(lines),
        "content": content,
    }


@registry.tool(
    description=(
        "Write or overwrite a test file. "
        "Pass file_path (absolute) and content (full Java source). "
        "Creates parent directories if they do not exist."
    ),
    require_human_approval=True,
    approval_context_fn=lambda args: (
        f"  File:    {args.get('file_path')}\n"
        f"  Action:  Write {len(args.get('content', '').splitlines())} lines of Java test code"
    ),
)
def write_test_file(file_path: str, content: str) -> dict:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        f.write(content)
    return {"status": "written", "file": file_path, "lines": len(content.splitlines())}


@registry.tool(
    description=(
        "Run a specific test class with Maven and JaCoCo to get line+branch coverage feedback. "
        "Pass repo_path (absolute path to the Maven project root containing pom.xml) "
        "and test_class (simple name, e.g. 'UserServiceTest'). "
        "Returns pass/fail counts and JaCoCo report path."
    )
)
def run_tests(repo_path: str, test_class: str) -> dict:
    cmd = (
        f"/opt/homebrew/bin/mvn test -Dtest={test_class} jacoco:report "
        f"-DskipITs -T 1C -q"
    )
    rc, stdout, stderr = _run(cmd, cwd=repo_path)

    report_path = os.path.join(repo_path, "target", "site", "jacoco", "index.html")
    surefire_dir = os.path.join(repo_path, "target", "surefire-reports")

    # Try to find test result summary
    summary = ""
    if os.path.exists(surefire_dir):
        for fname in os.listdir(surefire_dir):
            if test_class in fname and fname.endswith(".txt"):
                with open(os.path.join(surefire_dir, fname)) as f:
                    summary = f.read()[-2000:]
                break

    return {
        "exit_code": rc,
        "passed": rc == 0,
        "stdout_tail": stdout[-1500:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else "",
        "surefire_summary": summary,
        "jacoco_report": report_path if os.path.exists(report_path) else "not found",
    }


@registry.tool(
    description=(
        "Run PIT mutation coverage for a specific class and its test. "
        "Pass repo_path (absolute Maven project root), "
        "target_class (fully qualified, e.g. 'com.example.UserService'), "
        "and test_class (fully qualified, e.g. 'com.example.UserServiceTest'). "
        "Returns mutation score and surviving mutant details."
    ),
    require_human_approval=True,
    approval_context_fn=lambda args: (
        f"  Target class: {args.get('target_class')}\n"
        f"  Test class:   {args.get('test_class')}\n"
        f"  Action:       Run PIT mutation coverage (slow — takes 1-5 min)"
    ),
)
def run_mutation_coverage(repo_path: str, target_class: str, test_class: str) -> dict:
    cmd = (
        f"/opt/homebrew/bin/mvn pitest:mutationCoverage "
        f"-DtargetClasses={target_class} "
        f"-DtargetTests={test_class} "
        f"-T 1C -q"
    )
    rc, stdout, stderr = _run(cmd, cwd=repo_path)

    pit_dir = os.path.join(repo_path, "target", "pit-reports")
    report_path = pit_dir if os.path.exists(pit_dir) else "not found"

    return {
        "exit_code": rc,
        "passed": rc == 0,
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else "",
        "pit_report_dir": report_path,
    }


@registry.tool(
    description=(
        "Delete the temporary context files (.coversmith_issues.json and "
        ".coversmith_uncovered.json) created during this coverage run. "
        "Call this as the final step after coverage is complete or the run is abandoned."
    )
)
def cleanup_context() -> dict:
    deleted = []
    for path in [_ISSUES_FILE, _UNCOVERED_FILE]:
        if os.path.exists(path):
            os.remove(path)
            deleted.append(path)
    return {
        "deleted": deleted,
        "message": "Context files cleaned up." if deleted else "Nothing to clean up.",
    }
