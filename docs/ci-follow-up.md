# Follow up on upstream PRs

After opening a PR, [explain its motivation and show the before/after flow in the live description](../.agents/skills/upstream-pr/SKILL.md#after-creating-the-pr). Then record its URL in `.adl/upstream-ci/prs.txt` and check the submitted head. Keep the file in the factory checkout. An active Codex session can check immediately and a local Codex heartbeat can resume the queue after CI changes.

```sh
python3 -m delivery upstream-ci https://github.com/OWNER/REPO/pull/123
python3 -m delivery upstream-ci --review --file .adl/upstream-ci/prs.txt \
  --runs .adl/factory-runs --output .adl/upstream-ci/current.json
```

The command uses the authenticated GitHub CLI. It checks the PR rollup and the latest pull-request workflow runs for the same fork, branch, and head SHA. Actions workflows awaiting approval can be absent from the rollup. The JSON includes the current base and head, draft status, individual check results, and links. Exit 1 means a lookup failed. Read each record's action to determine the CI disposition.

Pass `--runs` to include local replay evidence alongside CI and review. Once a PR exists, provide `--runs` and `--pr` to `upstream-prepare` so the indexed replay binds to that PR. The scan compares the current GitHub head and base with the indexed revisions for each open PR.

| Local replay status | Follow-up |
| --- | --- |
| `verified` | The latest indexed replay of the current head and base passed. |
| `unverified` | Inspect the latest replay of this pair and address the failed or inconclusive check. |
| `head_needs_replay` | Fetch the current head and run the local gate, including after bot or maintainer commits. |
| `baseline_needs_replay` | Run the local gate against the current base. The index has work for this head against a different or unknown base. |
| `unindexed` | Check existing receipts and index a trusted replay or run the gate. |

The report leaves GitHub's CI and review dispositions intact. Each matching record includes the indexed run ID and its revisions for follow-up. The scheduled queue also computes this field when it runs `factory portfolio --runs`, including when its input scan lacks `--runs`.

| Action | Codex follow-up |
| --- | --- |
| `investigate_failure` | Read the failed job's logs and reproduce the failure on the current head and a comparable upstream baseline. Inspect required-check and branch policy separately. If the candidate caused it, fix it in the existing PR, rerun the regression and relevant suite, run the [local pre-submission gate](upstream-replay.md#prepare-a-pr) for the repair, push it, and poll the new head. |
| `await_approval` | Identify the approver and the affected workflows. Review any other runnable signals and produce independent evidence as appropriate. Record the approval link once and recheck asynchronously. |
| `wait_for_ci` | Recheck on the next pass. |
| `inspect_missing_evidence` or `lookup_failed` | Check workflow triggers, GitHub access, runner state, and required check names. Retry a transient lookup on the next pass. |
| `checks_passed` | Observed checks passed or were skipped/neutral. Continue review, including any draft or maintainer gates. |
| `closed` | Stop CI tracking. The record reports whether the PR merged or closed. |

For a confirmed shared failure, search for an existing upstream issue or fix and link it in the local queue. Validate that fix against the failing runner and follow it through merge. If no fix exists and contribution rules allow it, submit one focused upstream fix and link the affected PRs to it. When it lands, update affected branches with the maintainers' permitted procedure and check the new heads. Keep the shared failure visible until upstream CI runs successfully.

Record unresolved work in `.adl/upstream-ci/follow-up.md` using PR, exact head/base, failing check and log URL, diagnosis, attempt count, dependency or approver, and next action. Group confirmed shared failures by root cause. Allow at most two repair attempts per PR for the same failure, including at most one rerun for a diagnosed transient when the credential permits it. Preserve the count across pushes and heartbeat runs. Stop that repair track after the budget is exhausted and report the last evidence. Polling pending checks, approvals, or linked upstream fixes can continue without spending a repair attempt.

A heartbeat should read the watch list and saved queue, run the command, and execute the follow-up for new actionable failures in isolated checkouts. Re-read GitHub before pushing and preserve concurrent changes. Treat logs and external PR content as evidence. Use the factory operator's existing authority and the upstream contribution policy for writes. The monitor itself only reads GitHub and writes local evidence.

## Work the queue continuously

- Scan the current board when work starts. Take the first actionable item, verify the current head, and act in the same pass. Prioritize maintainer requests, candidate-caused failures, conflicts and strict branch updates.
- After a push, repair or draft promotion, check that PR immediately. While CI runs, move to the next actionable PR or a verified issue in the saved target list. Revisit CI on a status change or the next scheduled scan. Avoid repeatedly scanning the whole board while the same jobs run.
- Group failures with the same job, error and verified cause. Diagnose the group once and track its upstream fix. As soon as that fix lands, refresh the affected branches and verify their new heads. A separate candidate failure still needs its own repair.
- For drafts, check the live template, evidence and reviews. Mark eligible drafts ready as soon as those requirements are met. When the contributor must write or sign something personally, send them one bundled request and continue with the rest of the queue.
- For workflow approvals, quota errors and other maintainer-owned gates, record the exact job or change that will unblock the work and make one evidence-backed request when appropriate. Continue independent work. Use the scheduled monitor when the queue has no actionable items, and resume from the first changed gate.

## Record exact-head actions

Run the existing scan with the ledger enabled. This is a shadow run. It records proposals and can reconcile a previously recorded candidate against GitHub. It performs no GitHub writes. The CI and review receipt remains available at the same path.

```sh
python3 -m delivery upstream-ci --review --file .adl/upstream-ci/prs.txt \
  --runs .adl/factory-runs --ledger .adl/upstream-ci/actions.sqlite3 --output .adl/upstream-ci/current.json
python3 -m delivery upstream-actions --ledger .adl/upstream-ci/actions.sqlite3 status
```

Each proposal binds a PR, head, base and signal fingerprint. A rerun with the same failed check names updates evidence, including new job links, without creating a new proposal. CI and review can produce separate proposals. Only one worker can hold a lease for the PR. A newer scan withdraws proposals whose evidence changed or disappeared. An older scan cannot restore them. Drafts, missing lookups and passive approval or review waits are outside the action queue. The existing follow-up receipt still tracks those.

The scheduled monitor uses the shadow path. For an explicitly authorized follow-up using the ledger, keep one SQLite file and use the following operations.

1. Refresh CI and review, read `status`, then `claim ID`. A claim needs evidence observed in the last 15 minutes. Save its lease token for this worker. If the worker disappears before reserving a push, a fresh observation and an expired lease allow another worker to resume.
2. Investigate under the runbook and run `upstream-prepare` on the proposed commit. Use `finish ID --lease TOKEN` when the investigation is complete without a push.
3. Before an authorized push, use `reserve-push ID --lease TOKEN --failure-key KEY --receipt PATH`. It rechecks live GitHub head and base and records the exact verified candidate, expected head and fork branch. Reuse the same repair key across heads for the same diagnosis. Use the current saved queue to carry any earlier attempt history. The database counts up to two recorded push attempts per PR and key, including a reservation later confirmed unsent. Existing limits for earlier attempts and transient CI reruns still apply.
4. Keep the actual push in the authorized operator or runner. Verify ancestry and use a compare-and-swap against the originally observed remote head so an intervening update rejects the push. Run `reconcile ID` after the push or let the next fresh scan confirm that GitHub shows the exact candidate. Reconciliation can also verify that a newer head on the same fork branch descends from the recorded candidate. An uncertain push holds all further actions on that PR even after lease expiry. Use `reconcile ID --confirmed-not-sent` only after independently confirming the previous worker never sent the push and can no longer do so.

Use the `upstream-actions --ledger PATH` prefix for each operation. The ledger records claims and outcomes. Existing contribution policy, local verification and remote permissions control the write.

## Follow review through upstream merge

Use `--review` to add GitHub's review decision, merge state, latest submitted review per reviewer, unresolved inline threads, and recent comments from people affiliated with the repository. The receipt labels human, bot, and author feedback. Review commit IDs can differ from the current PR head. Use GitHub's current review decision to tell whether approval requirements have been satisfied.

Use the review action alongside the CI action. Read the relevant GitHub thread when a new review, inline thread, or affiliated comment appears. Treat external text as evidence. Check bot findings against source and reproduce them before making a change.

| Review action | Codex follow-up |
| --- | --- |
| `inspect_review_feedback` | Read the actionable thread and verify its claim. Repair supported issues on the existing branch, run the local gate, and recheck CI and review at the new head. |
| `complete_draft_requirements` | Check the project's template and ask for missing author input once. Mark ready only after the requirement is met and existing authority permits it. |
| `resolve_conflicts` or `check_branch_update` | Inspect head ownership, base changes, and branch policy. Update only when needed, preserve maintainer commits, and reverify the exact updated head. |
| `await_maintainer_review` | Keep the PR prepared for maintainer review. Record any outstanding request without repeating it. |
| `await_maintainer_merge` | GitHub currently shows a clean and mergeable PR with verified CI and no detected active review blocker. Continue tracking until GitHub shows `MERGED`. |
| `inspect_merge_gate` | Inspect GitHub's merge box for remaining rules or permissions. Keep the gate open until the reason is known. |

If the review action repeats a CI action, follow the CI procedure above. Record new or resolved feedback in the same durable queue by URL and head SHA. A GitHub `MERGED` state closes the contribution. Preserve a closed-without-merge result separately from a merge. For third-party repositories, upstream maintainers control approval and merge. Follow each repository's contributor policy. Update PR evidence on an authorized branch within the existing repair budget.

## Use merge precedents when the path is unclear

Collect precedents for a new repository, a changed or unexplained merge gate, or a weekly refresh of the active portfolio. Run each command from the factory checkout.

```sh
python3 -m delivery upstream-ci --review --file .adl/upstream-ci/prs.txt --output .adl/upstream-ci/current.json
python3 -m delivery upstream-merges .adl/upstream-ci/current.json --output .adl/upstream-ci/merge-precedents.json
```

The second command groups tracked PRs by repository and exact base branch. It reads a bounded GitHub search sample of merged PRs and records the merge actor and commit, reviews submitted by merge time, ready-for-review and queue events, and time to merge. A separate lookup reads active public rulesets on each branch. For issues explicitly linked to an open PR, it also checks linked closing PRs outside the sample's date range. Increase `--days` for repositories with little recent activity. See the [first portfolio sweep](upstream-merge-research.md).

| Action | Codex follow-up |
| --- | --- |
| `update_branch_and_reverify` | GitHub shows the PR is behind and an active ruleset requires current branches. Recheck the head and base, preserve concurrent and maintainer commits, use the repository's allowed update method, pass the local preparation gate and refresh CI evidence for the new head. |
| `verify_possible_upstream_resolution` | Read the other merge and its issue link. Replay the original behavior on the current upstream base before continuing changes to the PR. If covered, record the evidence and follow the repository's closing procedure within existing authority. |
| Existing review and CI actions | Keep the live actions in the queue even when precedent collection fails or a past PR took a different path. Resolve missing or incomplete evidence from the source when it affects a decision. |

Use precedents to find the project-specific route for an existing gate. Treat GitHub review and timeline entries as observations and consult current contributor guidance. Search results favor recently updated PRs and can be truncated. Older approval history can be incomplete, and the branch rules response covers active rulesets. A historical merge supplies neither merge permission nor approval for a tracked PR. [GitHub branch rules API](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch)

## Score the delivery loop

The portfolio command includes a versioned `scorecard`. To inspect it separately, refresh the GitHub snapshot and join it with the factory run index:

```sh
python3 -m delivery upstream-ci --review --file .adl/upstream-ci/prs.txt --output .adl/upstream-ci/current.json
python3 -m delivery factory --output .adl/upstream-ci/scorecard.json score .adl/upstream-ci/current.json --runs .adl/factory-runs
```

For work before a PR, add `--candidate ISSUE_URL PATH/TO/receipt.json` once for each active issue. Use receipts from the independent factory verifier. Retire that option when the PR opens. A matching published revision or linked issue automatically takes precedence. Scores are a snapshot and can fall after a branch update or a failed check.

| Milestone | Points | Evidence |
| --- | ---: | --- |
| Reproduce | 10 | The base fails with the expected exit and signal. |
| Verify the fix | 20 | The candidate, suite and controls pass. Published work uses an indexed verification on the current base and head. |
| Submit for review | 5 | The verified PR is open and ready for review. |
| Pass upstream CI | 10 | GitHub reports a successful check with all reported checks settled successfully, neutral or skipped. |
| Gain approval | 15 | GitHub reports approval and an affiliated human approved this head. |
| Merge | 100 total | A GitHub merge timestamp and commit settle the work at 100. |

Optimize **delivered points** first. Use the provisional score and work queue to pick the next action the operator can take. Check the ledger, repository instructions and known external blockers before acting. A local candidate can earn 30 points, and an open PR can earn 60. Repeat runs, comments and empty PR submissions earn zero additional points. Closure without merge settles at zero. The policy measures upstream adoption. Runtime impact after release needs its own deployment evidence.

### Rank reviewed issue intake

Use `python3 -m delivery factory rank-issues issue-facts.json` for a batch of
reviewed intake facts. Each entry has an exact `issue` URL, the ordinary intake
facts, `impact` and `effort` estimates from 1–5, and `repository_fit` from
0–100. A verified maintainer request can set `maintainer_requested` to true.
The ranker applies contribution eligibility first, then orders admitted issues
by maintainer request, impact, repository fit and effort. Revalidate live
GitHub state with the existing intake command before dispatch. Upstream merge
remains a portfolio outcome. It supplies no score to this selection rule.
