---
name: upstream-pr
description: Fix a reported upstream issue, open an evidenced pull request, and follow up on its CI.
---

1. Verify the issue against current upstream. Read the contribution rules, search for active PRs and claims, and record why the issue is eligible. Follow the project's route for maintainer-owned changes.
2. Set up an isolated local development checkout with the upstream toolchain and fixtures. Pin the base. Exercise the reported behavior through the real entry point before changing it.
3. Fix the cause. Choose the few scenarios most likely to expose a regression. Include an unchanged normal flow and the relevant boundary or failure behavior. Pin the candidate commit.
4. Run the [local pre-submission gate](../../../docs/upstream-replay.md#prepare-a-pr). A passing receipt must cover the live comparison, adjacent controls, and relevant existing suite. Use hosted CI for additional platform coverage. If the required local reproduction is unavailable, record the gap and stage the candidate.
5. Fill the upstream template and review the generated `pr.md`. Check the evidence links, before-and-after comparison, and coverage limits. Open the PR only when the verified SHA matches the published branch and contribution requirements are met.
6. Register the open PR and follow [upstream CI triage and repair](../../../docs/ci-follow-up.md). Start with the submitted SHA. Carry pending CI, approval, or upstream dependencies into the follow-up queue.
7. Keep one local decision log for a batch. Record the issue, disposition, base and candidate SHAs when applicable, PR URL, and evidence URL.

For an opted-in Pstack workflow, use `pstack-tdd` and `pstack-principle-fix-root-causes` for steps 2–3, `pstack-principle-prove-it-works` and `pstack-blast-radius` for steps 3–4, `pstack-technical-writing` for step 5, and `pstack-show-me-your-work` for step 7.
