import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import review_cases as cases


class HarvestCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.pr = "https://github.com/example/project/pull/12"
        self.base, self.target, self.head, self.tip = (c * 40 for c in "abcd")
        self.review = {"id": 51, "node_id": "PRR_51", "commit_id": self.head, "state": "CHANGES_REQUESTED",
                       "user": {"login": "maintainer", "type": "User"}, "author_association": "MEMBER",
                       "body": "The new argument doesn't reach the worker.", "submitted_at": "2026-11-10T01:02:03Z",
                       "html_url": f"{self.pr}#pullrequestreview-51"}
        self.metadata = {"head": {"sha": self.tip}, "base": {"sha": self.target, "ref": "main"},
                         "user": {"login": "submitter"}, "html_url": self.pr}
        self.reviews, self.events, self.inline = [self.review], [], []
        self.push = True
        self.remote = "git@github.com:example/project.git"
        self.ancestor = self.head
        self.addCleanup(patch.stopall)
        patch.object(cases, "git", side_effect=self.git).start()
        patch.object(cases, "gh_json", side_effect=self.github).start()

    def git(self, *args, cwd):
        if args == ("remote",):
            return b"origin\n"
        if args[0] == "remote":
            return self.remote.encode()
        if args[:2] == ("merge-base", "--all"):
            return self.base.encode()
        self.assertEqual(args, ("merge-base", self.tip, self.head))
        return self.ancestor.encode()

    def github(self, *args):
        if args[1] == "graphql":
            return {"data": {"node": {"authorCanPushToRepository": self.push}}}
        if "comments?" in args[-1]:
            return [self.inline]
        if "reviews?" in args[-1]:
            return [self.reviews]
        if "timeline?" in args[-1]:
            return [self.events]
        self.assertEqual(args[-1], "repos/example/project/pulls/12")
        return self.metadata

    def harvest(self, split="holdout"):
        return cases.harvest(self.folder, self.pr, 51, split, self.folder)

    def test_preserves_pre_repair_head_and_original_merge_base(self):
        case = self.harvest()
        self.assertEqual((case["base"], case["head"], case["target_base"]), (self.base, self.head, self.target))
        self.assertEqual((case["expected"], case["evidence"]), ("changes", self.review["html_url"]))
        self.assertEqual(self.harvest(), case)
        self.assertEqual(cases.load_cases(self.folder), [case])
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.harvest("development")

    def test_rejects_ambiguous_superseded_and_dismissed_verdicts(self):
        other = dict(self.review, id=52, state="APPROVED")
        for login in ("maintainer", "maintainer-two"):
            with self.subTest(login=login):
                self.reviews = [self.review, dict(other, user={"login": login, "type": "User"})]
                with self.assertRaisesRegex(ValueError, "unambiguous"):
                    self.harvest()
        self.reviews = [dict(self.review, state="DISMISSED")]
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            self.harvest()
        # A later decision about the repaired commit labels a different case.
        self.reviews = [self.review, dict(other, commit_id=self.tip)]
        self.assertEqual(self.harvest()["expected"], "changes")

    def test_rejects_nonhuman_self_and_insufficient_permissions(self):
        for account in ({"type": "Bot", "login": "robot"}, {"type": "User", "login": "SUBMITTER"},
                        {"type": "User", "login": "all-hands-bot"}):
            with self.subTest(account=account):
                self.reviews = [dict(self.review, user=account)]
                with self.assertRaisesRegex(ValueError, "independent"):
                    self.harvest()
        self.reviews = [self.review]
        self.push = False
        with self.assertRaisesRegex(ValueError, "push access"):
            self.harvest()

    def test_inline_findings_from_selected_reviewer(self):
        self.review["body"] = ""
        comment = {"user": self.review["user"], "body": "Wrong option", "path": "worker.py"}
        self.inline = [comment, dict(comment, body="Error on retry"), dict(comment, path="entry.py"),
                       dict(comment, path="third.py", user={"login": "reader"}),
                       dict(comment, path="other.py", in_reply_to_id=222)]
        case = self.harvest()
        self.assertEqual(case["finding_paths"], ["entry.py", "worker.py"])
        self.assertIn("worker.py: Wrong option", case["rationale"])

    def test_self_declared_automation_from_write_authorized_human_account(self):
        for header in ("🤖 Automated review (CASE) at `49cac92770`", "## AI-generated code review",
                       "PR Desk (Eric's bot): review record"):
            with self.subTest(header=header):
                self.reviews = [dict(self.review, body=header + "\n\nPlease handle these two failures.")]
                with self.assertRaisesRegex(ValueError, "independent"):
                    self.harvest()

    def test_rejects_retargeted_or_detached_review(self):
        self.events = [{"event": "base_ref_changed", "created_at": self.review["submitted_at"]}]
        with self.assertRaisesRegex(ValueError, "retargeted"):
            self.harvest()
        self.events = []
        self.ancestor = self.base
        with self.assertRaisesRegex(ValueError, "outside"):
            self.harvest()

    def test_rejects_wrong_checkout_and_mislabeled_evidence(self):
        self.remote = "https://github.com.example.org/example/project.git"
        with self.assertRaisesRegex(ValueError, "remote"):
            self.harvest()
        self.remote = "ssh://git@github.com/Example/project.git"
        case = self.harvest()
        case["evidence"] = f"{self.pr}#pullrequestreview-24"
        (self.folder / "pr-12.json").write_text(json.dumps(case))
        with self.assertRaisesRegex(ValueError, "invalid frozen"):
            cases.load_cases(self.folder)
