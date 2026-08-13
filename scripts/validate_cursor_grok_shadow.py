"""Low-risk Shadow validation for the cursor-grok executor.

Runs entirely on a throwaway sandbox git repo (/Users/pojian/.cp-shadow-wt) and the
local control-plane database. It never touches the director / Owner working tree,
never pushes, deploys, or sends anything externally, and uses the offline
FakeGrokClient so no paid API or secret is involved.

Produces a DRAFT -> READY -> CLAIMED -> RUNNING -> REVIEW -> DONE flow and prints the
resulting task / lease / run / report / review IDs.
"""
import json
import subprocess
import uuid
from pathlib import Path

from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType, TaskState
from control_plane.executors import build_cursor_grok_executor
from control_plane.services import LeaseDispatcher, ReviewGate, TaskRegistry, task_from_dict
from control_plane.storage import Repository

SCRATCH = Path("/Users/pojian/.cp-shadow-wt")
DB = Path("/Users/pojian/repos/director-control-plane-cg/var/control-plane.sqlite3")
TASK_ID = "TASK-SHADOW-CG-001"


def _git(*args, cwd):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def ensure_scratch():
    if not (SCRATCH / ".git").exists():
        SCRATCH.mkdir(parents=True, exist_ok=True)
        _git("init", "-q", cwd=SCRATCH)
        _git("config", "user.email", "shadow@local", cwd=SCRATCH)
        _git("config", "user.name", "shadow", cwd=SCRATCH)
        (SCRATCH / "README.md").write_text("# cp-shadow sandbox\n", encoding="utf-8")
        _git("add", "-A", cwd=SCRATCH)
        _git("commit", "-qm", "baseline", cwd=SCRATCH)
    head = _git("rev-parse", "--short", "HEAD", cwd=SCRATCH).stdout.strip()
    common = _git("rev-parse", "--absolute-git-dir", cwd=SCRATCH).stdout.strip()
    return head, common


def main():
    baseline, common = ensure_scratch()
    repo = Repository(DB)
    repo.migrate()
    registry = TaskRegistry(repo)
    dispatcher = LeaseDispatcher(repo)

    repo.upsert_project(ProjectConfig(
        id="cp-shadow", name="cp-shadow-sandbox", kind="control_plane", owner="Owner",
        root=SCRATCH, ledger=SCRATCH / "TASKS.md", status=SCRATCH / "STATE.md",
        knowledge_roots=[], enabled_agents=list(AgentType),
    ))
    # Register cursor-grok as a low-risk backup executor for the real control-plane
    # project AND for the sandbox project. Upsert is idempotent.
    dispatcher.register_executor("cursor-grok", ["control-panel", "cp-shadow"], "low")
    dispatcher.set_project_baseline("cp-shadow", baseline, "planner")

    if repo.get_task(TASK_ID) is None:
        registry.register(task_from_dict({
            "id": TASK_ID, "projectId": "cp-shadow", "title": "Shadow: cursor-grok low-risk execution",
            "objective": "Validate cursor-grok executor end-to-end on an isolated sandbox repo.",
            "scope": ["Create one scoped artifact file inside the sandbox workspace root and commit it "
                      "in an isolated git worktree."],
            "acceptance": [
                "A scoped artifact file was created inside the sandbox workspace root.",
                "The change was committed in an isolated git worktree.",
                "No other files were modified and no external action occurred.",
            ],
            "priority": "P3", "riskLevel": "low", "allowedExecutors": ["cursor-grok"],
            "workspaceRoots": [str(SCRATCH)], "dependencies": [],
        }), "planner")

    task = repo.get_task(TASK_ID)
    if task["state"] == "DRAFT":
        registry.transition(TASK_ID, TaskState.READY, task["version"], "policy", "shadow ready")

    wt = SCRATCH.parent / "{}-wt-{}".format(SCRATCH.name, uuid.uuid4().hex[:8])
    _git("worktree", "add", "-q", str(wt), "-b", "shadow/{}".format(uuid.uuid4().hex[:8]), cwd=SCRATCH)

    executor = build_cursor_grok_executor(repo, executor_id="cursor-grok")
    result = executor.execute(TASK_ID, wt, common, baseline, "shadow-cg")

    report = repo.get_executor_report(result.report_id)["report"]
    review = ReviewGate(repo).review(report, "codex-review", "shadow-review")

    # Tidy the throwaway worktree; the branch + commit stay in the sandbox repo.
    _git("worktree", "remove", "-f", str(wt), cwd=SCRATCH)

    summary = {
        "task_id": TASK_ID,
        "lease_id": result.lease_id,
        "run_id": result.run_id,
        "report_id": result.report_id,
        "review_id": review["review"]["id"],
        "review_outcome": review["review"]["outcome"],
        "task_state": repo.get_task(TASK_ID)["state"],
        "commit_ref": report.get("commitRef"),
        "executor_registered": "cursor-grok -> control-panel,cp-shadow (low)",
        "baseline": baseline,
        "success": result.success,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
