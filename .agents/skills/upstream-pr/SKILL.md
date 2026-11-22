---
name: upstream-pr
description: Fix a reported upstream issue, open an evidenced pull request, and follow up on its CI and review through upstream merge.
---

1. Verify the issue against current upstream. Read the contribution rules, search for active PRs and claims, and record why the issue is eligible. Follow the project's route for maintainer-owned changes.
2. Set up an isolated local development checkout with the upstream toolchain and fixtures. Pin the base. Exercise the reported behavior through the real entry point before changing it.
3. Fix the cause. Choose the few scenarios most likely to expose a regression. Include an unchanged normal flow and the relevant boundary or failure behavior. Pin the candidate commit.
4. Run the [local pre-submission gate](../../../docs/upstream-replay.md#prepare-a-pr). A passing receipt must cover the live comparison, adjacent controls, and relevant existing suite. Use hosted CI for additional platform coverage. If the required local reproduction is unavailable, record the gap and stage the candidate.
5. Fill the upstream template and review the generated `pr.md`. Check the evidence links, before-and-after comparison, and coverage limits. Open the PR only when the verified SHA matches the published branch and contribution requirements are met.
6. Once GitHub returns the PR URL, [update its description](#after-creating-the-pr). Register the open PR and follow [upstream CI, review, and merge](../../../docs/ci-follow-up.md). Start with the submitted SHA. Collect merge precedents for new upstreams or changed gates, then reconcile them with live branch rules. Carry pending CI, review, or upstream dependencies into the follow-up queue until GitHub records the outcome.
7. Keep one local decision log for a batch. Record the issue, disposition, base and candidate SHAs when applicable, PR URL, and evidence URL.

For an opted-in Pstack workflow, use `pstack-tdd` and `pstack-principle-fix-root-causes` for steps 2–3, `pstack-principle-prove-it-works` and `pstack-blast-radius` for steps 3–4, `pstack-technical-writing` for step 5, and `pstack-show-me-your-work` for step 7.

## After creating the PR

Read the **live** body and head with `gh pr view "$pr_url" --json body,headRefOid`. Work from that body, the issue, and the verified before/after observations for the published head.

In the template’s existing summary or details section, explain in one or two sentences who encounters the problem, what goes wrong for them, and why the new behavior matters. Replace an implementation recap there. If the body already explains the motivation, keep that wording. Put a small fenced `text` diagram beside it. Trace the same input or action on both lines, ending at the observable difference. For documentation or test changes, show the reader’s or contributor’s workflow. For example:

```text
Before  README-only edit -> load workspace -> plan tasks -> no checks
After   README-only edit -> no checks
```

Keep upstream headings, issue links, evidence, checklists, disclosures, human-authored notes and bot sections intact. If the upstream template restricts the layout, use its permitted free-text field. Skip the write if the live body already has the rationale and an accurate flow.

Save the revised body to a file. Immediately before editing, re-read the body and head. If either changed, reconcile with the latest text and evidence first. Apply with `gh pr edit "$pr_url" --body-file "$revised_body"`, then read the description back to verify the rationale, diagram and surrounding content. On retry, update the existing explanation in place.
