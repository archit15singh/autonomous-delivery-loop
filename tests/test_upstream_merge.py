import unittest
from unittest.mock import patch

from delivery.upstream_merge import advise, merge_precedents

URL = "https://github.com/owner/project/pull/123"
PEER_URL = "https://github.com/owner/project/pull/122"
ISSUE = "https://github.com/owner/project/issues/100"
MERGED = "2026-11-20T12:00:00Z"


class UpstreamMergeTests(unittest.TestCase):
    def setUp(self):
        self.pr = {
            "url": URL, "base_branch": "dev/next", "state": "OPEN", "head": "a" * 40,
            "action": "await_approval", "review": {"action": "check_branch_update"},
            "linked_issues": [ISSUE],
        }

    @patch("delivery.upstream_merge.gh_json")
    def test_precedent_never_overrides_current_gates(self, github):
        review = {"state": "APPROVED", "submittedAt": MERGED, "authorAssociation": "MEMBER",
                  "commit": None, "url": PEER_URL + "#approval"}
        peer = {
            "url": PEER_URL, "title": "Fix reported behavior", "state": "MERGED",
            "createdAt": "2026-11-18T12:00:00Z", "mergedAt": MERGED,
            "headRefOid": "b" * 40, "isCrossRepository": True, "authorAssociation": "NONE",
            "author": {"login": "contributor", "__typename": "User"}, "mergedBy": None,
            "mergeCommit": {"oid": "c" * 40},
            "closingIssuesReferences": {"nodes": [{"url": ISSUE}], "pageInfo": {"hasNextPage": False}},
            "timelineItems": {"nodes": [], "pageInfo": {"hasNextPage": False}},
            "reviews": {"nodes": [
                {**review, "author": {"login": "app", "__typename": "Bot"}},
                {**review, "author": {"login": "contributor", "__typename": "User"}},
                {**review, "author": {"login": "reviewer", "__typename": "User"},
                 "submittedAt": "2026-11-21T00:00:00Z"},
            ], "pageInfo": {"hasPreviousPage": False}},
        }
        github.side_effect = [
            {"data": {"search": {"issueCount": 10, "pageInfo": {"hasNextPage": True},
                                  "nodes": [peer, {**peer, "url": URL}]}}},
            [[{"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": "test"}],
            }}, {"type": "pull_request", "parameters": {
                "required_approving_review_count": 1, "require_code_owner_review": True,
                "required_review_thread_resolution": False, "allowed_merge_methods": ["squash"],
            }}]],
            {"data": {"i0": {"issue": {"closedByPullRequestsReferences": {
                "nodes": [{"url": PEER_URL, "state": "MERGED", "mergeCommit": {"oid": "c" * 40}},
                          {"url": URL, "state": "OPEN", "mergeCommit": None}],
                "pageInfo": {"hasNextPage": False},
            }}}}},
        ]
        branch, = merge_precedents([self.pr], days=60, limit=2)["branches"]
        self.assertIn('base:"dev/next"', branch["search"])
        self.assertIn("branches/dev%2Fnext", github.call_args_list[1].args[-1])
        self.assertTrue(branch["sample_truncated"])
        self.assertEqual(branch["active_rulesets"]["required_checks"], ["test"])
        self.assertTrue(branch["active_rulesets"]["require_code_owner_review"])
        self.assertEqual(len(branch["sample"]), 1)
        self.assertEqual(branch["external_path"]["with_observed_human_approval"], 0)
        self.assertEqual(branch["external_path"]["median_days_to_merge"], 2)
        tracked, = branch["tracked_prs"]
        self.assertEqual(tracked["possible_alternative_merges"][0]["issue"], ISSUE)
        self.assertEqual(tracked["actions"], [
            "verify_possible_upstream_resolution", "update_branch_and_reverify", "await_approval",
        ])

    @patch("delivery.upstream_merge.gh_json", side_effect=OSError("GitHub unavailable"))
    def test_lookup_failure_preserves_live_gate_and_records_error(self, github):
        branch, = merge_precedents([self.pr], days=60, limit=2)["branches"]
        self.assertIn("GitHub unavailable", branch["error"])
        self.assertEqual(branch["tracked_prs"][0]["actions"], ["check_branch_update", "await_approval"])
        self.assertEqual(advise({**self.pr, "state": "CLOSED"}, {})["actions"], [])
