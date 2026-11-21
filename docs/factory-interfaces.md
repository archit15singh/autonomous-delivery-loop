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
Include `reproduction` and add `technical_brief` when an interface decision needs
review. Keep the brief and approval on the operator-controlled runner.

```sh
python3 -m delivery factory issue-run "$ISSUE" "$SPEC" \\
  --ledger .adl/factory.sqlite3 --receipts .adl/issue-runs
python3 -m delivery factory --output .adl/approval.json approve-issue "$ISSUE" "$SPEC"
python3 -m delivery factory issue-run "$ISSUE" "$SPEC" \\
  --approval .adl/approval.json --ledger .adl/factory.sqlite3 --receipts .adl/issue-runs
```

Run the dispatcher from reviewed main on macOS with authenticated GitHub and
Codex CLIs. An edited issue, contract, or main revision invalidates the approval.
Keep one durable SQLite ledger across invocations. The dispatcher holds a
reservation before starting the agent. A retry reports the existing reservation
and any published PR. Investigate an unfinished reservation against the local
receipts and GitHub branch before taking another action. Candidate execution
denies writes, home directory reads and non-loopback networking.
