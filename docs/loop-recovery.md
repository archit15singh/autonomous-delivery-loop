# Resume a factory loop

Keep the objective, acceptance check, latest verified milestone, unresolved decisions, and next action in a short local note at `.adl/upstream-ci/active.md`. Update it when a milestone or the next action changes. Include the receipt path and exact revision for verified work. Include the job URL or process handle for work still running. Record who owns a decision and the scope of any approval. For concurrent tasks, give each a separate note and pass its path with `--note`.

Run this from the canonical checkout after compaction or in a fresh session:

```sh
python3 -m delivery factory resume
python3 -m delivery factory resume --pr https://github.com/OWNER/REPO/pull/123
```

For work in another checkout, pass `--workspace` for the code you are changing and `--state-dir` for the canonical factory's existing `.adl` directory. For work before a PR exists, use the first command, inspect the milestone receipt, poll any recorded job, and rerun the smallest acceptance check that exercises the requested behavior. The underlying workflow runner already validates its pinned inputs and completed artifacts when resuming its run directory.

For a PR, the second command reads GitHub again, matches the run index to the current revisions, and records a fresh local observation. It reports active leases, reserved pushes and repair counts for that PR. Reconcile an uncertain push before another attempt. A lease identifies an existing claim. Poll the actual worker or job handle separately to determine whether work is running. A failed lookup returns a nonzero status. Follow the [existing claim and repair procedure](ci-follow-up.md) for external actions.

Keep the note small enough to read in one pass. Put logs with the receipt, shared failure diagnoses in `follow-up.md`, and action ownership in SQLite. A fresh session should be able to recover the acceptance check, find its evidence, and choose the same next action. Test this by running recovery from a new process and comparing its revisions, decisions and holds with the original run.

## Design evidence

Codex Goals preserve an objective within a thread. OpenAI's long-horizon example also kept acceptance criteria, decisions and milestone evidence in files that a later turn could reopen. The factory keeps those few pieces of human context in the note and obtains changing facts from their owners. [Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex) · [Run long horizon tasks with Codex](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)

Anthropic observed that fresh sessions recovered more reliably when they read progress and Git history and exercised a real user path. Here the corresponding check is the same acceptance probe used before interruption, tied to the current revision. [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)
