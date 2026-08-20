import json
import unittest
from pathlib import Path

from control_plane.domain.models import ApprovalClass, TaskState
from control_plane.services import DecisionPolicyEngine, TaskRegistry, TaskValidationError, task_from_dict
from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType
from control_plane.storage import Repository
import tempfile


REPO = Path(__file__).resolve().parents[1]


class TaskApprovalContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = Repository(self.root / "control-plane.sqlite3")
        self.repository.migrate()
        self.repository.upsert_project(ProjectConfig(
            id="panel", name="Panel", kind="control_plane", owner="Owner", root=self.root,
            ledger=self.root / "TASK_QUEUE.md", status=self.root / "CURRENT_STATE.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        ))
        self.registry = TaskRegistry(self.repository)
        self.policy = DecisionPolicyEngine(self.repository)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **updates):
        body = {
            "id": "TASK-R0-001",
            "projectId": "panel",
            "title": "Approval contract",
            "objective": "Prove owner approval is machine-checked.",
            "scope": ["Schema", "Domain", "Policy"],
            "acceptance": ["Missing refs cannot become READY"],
            "priority": "P1",
            "riskLevel": "low",
            "allowedExecutors": ["codex"],
            "workspaceRoots": [str(self.root)],
            "dependencies": [],
        }
        body.update(updates)
        return body

    def test_schema_freezes_approval_enum_and_forbids_unknown_properties(self):
        schema = json.loads((REPO / "config" / "task.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["approvalClass"]["enum"],
            ["none", "knowledge_write", "database_write", "direction", "acceptance_change"],
        )
        self.assertEqual(schema["properties"]["approvalClass"]["default"], "none")
        self.assertEqual(schema["properties"]["ownerApprovalRef"]["minLength"], 1)
        self.assertNotIn("approvalClass", schema["required"])
        self.assertNotIn("ownerApprovalRef", schema["required"])

    def test_legacy_payload_defaults_to_none(self):
        task = task_from_dict(self.payload())
        self.assertEqual(task.approval_class, ApprovalClass.NONE)
        self.assertIsNone(task.owner_approval_ref)
        stored = self.registry.register(task, "codex")
        self.assertEqual(stored["approval_class"], "none")
        self.assertIsNone(stored["owner_approval_ref"])

    def test_spoofed_fields_cannot_bypass_owner_approval_ref(self):
        for spoof in (
            {"ownerApproved": True},
            {"approved": True},
            {"owner_approval_ref": "OWNER-FAKE"},
            {"approvalGranted": "yes"},
            {"ownerApproval": "OWNER-FAKE"},
        ):
            payload = self.payload(approvalClass="database_write", **spoof)
            with self.assertRaisesRegex(TaskValidationError, "unknown task fields"):
                task_from_dict(payload)

    def test_missing_owner_approval_ref_cannot_become_ready(self):
        task = task_from_dict(self.payload(id="TASK-DB-001", approvalClass="database_write"))
        self.registry.register(task, "codex")
        evaluation = self.policy.evaluate("TASK-DB-001", _facts())
        self.assertEqual(evaluation["outcome"], "BLOCKED")
        self.assertIn("block.owner_approval_missing", evaluation["matchedRules"])
        with self.assertRaisesRegex(TaskValidationError, "ownerApprovalRef is required before READY"):
            self.registry.transition("TASK-DB-001", TaskState.READY, 1, "codex", "bypass")
        self.assertEqual(self.repository.get_task("TASK-DB-001")["state"], "DRAFT")

    def test_database_write_with_owner_ref_can_be_ready(self):
        task = task_from_dict(self.payload(
            id="TASK-DB-002", approvalClass="database_write", ownerApprovalRef="OWNER-OK-1",
        ))
        self.registry.register(task, "codex")
        result = self.policy.decide("TASK-DB-002", _facts(), 1, "codex")
        self.assertEqual(result["task"]["state"], "READY")
        self.assertEqual(result["task"]["owner_approval_ref"], "OWNER-OK-1")


def _facts():
    from control_plane.services import decision_facts_from_dict
    return decision_facts_from_dict({
        "architectureChange": False, "productionChange": False, "permissionChange": False,
        "externalCommunication": False, "paidAction": False, "destructiveAction": False,
        "releaseAction": False, "scopeExpansion": False, "safetyEvidenceComplete": True,
        "baselineKnown": True, "workspaceAuthorized": True, "acceptanceComplete": True,
    })


if __name__ == "__main__":
    unittest.main()
