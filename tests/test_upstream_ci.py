import unittest
from unittest.mock import patch

from delivery.upstream_ci import inspect_prs, next_action, signal


URL = "https://github.com/owner/project/pull/123"
HEAD = "a" * 40


class UpstreamCITests(unittest.TestCase):
    def setUp(self):
        self.pr = {
            "state": "OPEN", "isDraft": False, "headRefOid": HEAD,
            "baseRefOid": "b" * 40, "headRefName": "fix",
            "headRepository": {"nameWithOwner": "author/project"},
            "statusCheckRollup": [{"context": "Docs", "state": "SUCCESS"}],
        }

    def run_data(self, number, state, **changes):
        return {
            "head_sha": HEAD, "head_branch": "fix",
            "head_repository": {"full_name": "author/project"},
            "pull_requests": [], "workflow_id": 1, "run_number": number,
            "name": "CI", "conclusion": state, "status": "completed",
            "html_url": f"https://github.com/owner/project/actions/runs/{number}",
            **changes,
        }

    @patch("delivery.upstream_ci.gh_json")
    def test_approval_missing_from_pr_rollup_is_visible(self, github):
        github.side_effect = [self.pr, [{"workflow_runs": [self.run_data(1, "action_required")]}]]
        record, = inspect_prs([URL, URL])
        self.assertEqual(record["action"], "await_approval")
        self.assertEqual(record["head"], HEAD)
        self.assertEqual(github.call_count, 2)
        self.assertIn(f"head_sha={HEAD}&event=pull_request", github.call_args.args[-1])

    @patch("delivery.upstream_ci.gh_json")
    def test_uses_latest_workflow_for_this_pr_and_head(self, github):
        old = self.run_data(1, "failure")
        success = self.run_data(2, "success")
        other = [
            self.run_data(3, "failure", head_sha="c" * 40),
            self.run_data(4, "failure", head_branch="elsewhere"),
            self.run_data(5, "failure", pull_requests=[{"number": 456}]),
            self.run_data(6, "failure", head_repository={"full_name": "other/project"}),
        ]
        github.side_effect = [self.pr, [{"workflow_runs": other + [success]}, {"workflow_runs": [old]}]]
        record, = inspect_prs([URL])
        self.assertEqual(record["action"], "checks_passed")
        self.assertEqual(len(record["signals"]), 2)

    @patch("delivery.upstream_ci.gh_json")
    def test_lookup_error_cannot_pass(self, github):
        github.side_effect = [self.pr, OSError("no access")]
        record, = inspect_prs([URL])
        self.assertEqual(record["action"], "lookup_failed")

    @patch("delivery.upstream_ci.gh_json")
    def test_merged_pr_needs_no_further_ci_requests(self, github):
        github.return_value = {**self.pr, "state": "MERGED"}
        record, = inspect_prs([URL])
        self.assertEqual(record["action"], "closed")
        github.assert_called_once()

    def test_failure_pending_and_missing_evidence(self):
        cases = [
            (["action_required", "timed_out"], "investigate_failure"),
            (["success", "queued"], "wait_for_ci"),
            (["success", "cancelled"], "inspect_missing_evidence"),
            (["skipped", "neutral"], "inspect_missing_evidence"),
            ([], "inspect_missing_evidence"),
        ]
        for states, expected in cases:
            with self.subTest(states=states):
                self.assertEqual(next_action([signal("check", state, None) for state in states]), expected)
