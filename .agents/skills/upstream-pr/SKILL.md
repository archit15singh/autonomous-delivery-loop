---
name: upstream-pr
description: Fix a reported upstream issue, open an evidenced pull request, and follow up on its CI.
---

1. Verify the issue against current upstream. Read the contribution rules, search for active PRs and claims, and record why the issue is eligible. Follow the project's route for maintainer-owned changes.
2. Pin the upstream base. Exercise the issue through its real entry point before changing it. Use the smallest regression check that distinguishes the failure from an environment problem.
3. Fix the cause and test the adjacent behavior the patch could affect. Pin the candidate commit and list the implementation and regression files.
4. Run `python3 -m delivery upstream-replay` with a reviewed contract when the same command can run in both checkouts. For a platform-specific setup, use the project's test runner and record the exact base, candidate, and commands. Keep the raw logs with the receipt.
5. Follow the project's PR template. Explain what caused the failure, show one before-and-after visual, link the hosted run and affected issue, and name any test limits.
6. Register the open PR and follow [upstream CI triage and repair](../../../docs/ci-follow-up.md). Start with the submitted SHA. Carry pending CI, approval, or upstream dependencies into the follow-up queue.
7. Keep one local decision log for a batch. Record the issue, disposition, base and candidate SHAs when applicable, PR URL, and evidence URL.

For an opted-in Pstack workflow, use `pstack-tdd` and `pstack-principle-fix-root-causes` for steps 2–3, `pstack-principle-prove-it-works` and `pstack-blast-radius` for steps 3–4, `pstack-technical-writing` for step 5, and `pstack-show-me-your-work` for step 7.
