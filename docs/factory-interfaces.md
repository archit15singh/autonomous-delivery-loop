# Factory interfaces

| Term | Meaning and evidence |
| --- | --- |
| Issue snapshot | The GitHub issue identity, title, body and last update. `factory issue-run` hashes this snapshot before dispatch and again before publication. |
| Approved outcome | The operator-approved issue snapshot, exact specification bytes, and base commit. `factory approve-issue` records the approval. |
| Candidate | The exact commit produced by applying a scope-checked Codex patch to the approved base. `delivery propose` exports the patch and execution recipe. |
| Verified candidate | A candidate whose independent staging report passes each approved probe and matches its revision and deployment ID. `delivery stage` records the verdict. |
| Merged PR | GitHub reports `MERGED` and supplies a merge commit. A draft or successful CI check is a separate state. |
| Verified production deployment | `factory outcome-report` reports a verified observation for the configured production environment and the exact deployment ID and revision. |

The issue dispatcher reads GitHub issue state and hands Codex an approved outcome
contract. Codex may change the pilot service. The trusted base owns the tests and
runtime verifier. Publication consumes the resulting candidate and independent
receipt. GitHub owns draft and merge state, and outcome reporting reads those
states alongside deployment observations.

## Owned issue pilot

Opt in by applying the `adl-candidate` label to one owned issue. Use a local
contract with the usual outcome, three acceptance examples, and HTTP probes.
Include `reproduction` and `reproduction_path` and add `technical_brief` when an interface decision needs
review. Keep the brief and approval on the operator-controlled runner.

```sh
python3 -m delivery factory issue-run "$ISSUE" "$SPEC" \\
  --ledger .adl/factory.sqlite3 --receipts .adl/issue-runs
python3 -m delivery factory --output .adl/approval.json approve-issue "$ISSUE" "$SPEC"
python3 -m delivery factory issue-run "$ISSUE" "$SPEC" \\
  --approval .adl/approval.json --ledger .adl/factory.sqlite3 --receipts .adl/issue-runs
```

Run the dispatcher from reviewed main on macOS with authenticated GitHub and
Codex CLIs and a Python installation outside the user home directory. An edited issue, contract, or main revision invalidates the approval.
Keep one durable SQLite ledger across invocations. The dispatcher holds a
reservation before starting the agent. A retry can finish an interrupted publication from its verified checkpoint or report the existing reservation
and any published PR. Investigate an unfinished reservation against the local
receipts and GitHub branch before taking another action. Candidate execution
denies writes, home directory reads and non-loopback networking.

## Review and release feedback

Run factory cold-review PR_URL from a trusted checkout after fetching the exact
PR and base refs. The read-only Codex pass uses the base checkout and the candidate
diff. Save the report locally. Use factory review-correction REPORT KEY RATIONALE
to record an operator's explicit correction while the report's head is current.

Use factory review-replay CORRECTION ORIGINAL CONTROL OLD_SKILL NEW_SKILL to
rerun both reviewed skills on the original and held-out changes. CONTROL names
the held-out PR, base, head, finding path and expected finding key. The old review must
reproduce the rejected finding. The proposed review must drop it and both must
retain the valid control. A new finding on the corrected path requires another human adjudication. Evaluate skill changes in their own reviewed PR.

Use factory staging-signal RUN_ID --ledger .adl/factory.sqlite3 to read a
completed main delivery run and its exact hosted-staging evidence. An opted-in
operator or scheduler can pass --file-issue for actionable probe failures. Keep
one shared ledger for all runs. Investigations enter the owned issue tracker
without opting in to implementation. Healthy, inconclusive and wrong-identity
evidence cannot trigger work.

Release observations from this entry point are hosted-staging observations.
A production rollout needs a separately configured and authorized environment
and a trusted collector. Keep billed cost and hands-on human time unknown
until you have their measurements.

To rehearse the investigation path, manually dispatch the Delivery evidence
workflow on main. The rehearsal expects one deliberately wrong health result
from the live staging service. Read its receipt with staging-signal RUN_ID
--drill. Apply --file-issue only when rehearsing ticket publication. The
rehearsal has its own signal identity. Ordinary release observation accepts
only push runs.
