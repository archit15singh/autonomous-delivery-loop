# Local verification audit

This audit covers the 26 upstream PRs tracked on November 21, 2026, including three OpenHands SDK drafts. All 26 descriptions included concrete test results or linked replay evidence. At intake, 25 named the then-current candidate SHA. Promptfoo #12535 had a newer maintainer commit. The audit identifies what the evidence shows about execution and lists meaningful gaps. These PRs predate the [local pre-submission gate](upstream-replay.md#prepare-a-pr).

| PR | Evidence reviewed | Scope or gap |
| --- | --- | --- |
| [Herdr Core #352](https://github.com/herdrdev/herdr-core/pull/352) | Built CLI and isolated PATH replay. Ran skill, docs, and help tests. | Installed-app detection used a recording fixture. |
| [Herdr Core #353](https://github.com/herdrdev/herdr-core/pull/353) | Local macOS sweep tests. Hosted Linux shifted the boot clock and ran the exact test. | The reported clock gap was reproduced on the Linux runner. |
| [Herdr Core #356](https://github.com/herdrdev/herdr-core/pull/356) | Local remote tests. Hosted two-core Ghostty reconnect reproduced the scrollback failure and verified recovery. | The local two-core setup timed out. |
| [Herdr Core #362](https://github.com/herdrdev/herdr-core/pull/362) | Local Codex skill discovery and hosted compiled CLI check. | Tested routing metadata. Model routing behavior was outside the replay. |
| [Herdr Core #363](https://github.com/herdrdev/herdr-core/pull/363) | Hosted compiled CLI reproduced the old behavior and exercised table output, JSON defaults, and conflicting flags. | The live isolated PTY replay was hosted. |
| [Herdr App #1295](https://github.com/herdrdev/herdr-app/pull/1295) | Local scratch app and Core opened the actual agent menu from a background PTY. Platform jobs supplied further coverage. | Isolated logging shell fixture. |
| [Herdr App #1297](https://github.com/herdrdev/herdr-app/pull/1297) | Local native Core Graphics and AppKit event replay. The macOS parser suite passed. | Full Espanso-to-terminal flow remains manual. |
| [Herdr App #1300](https://github.com/herdrdev/herdr-app/pull/1300) | Local window tests. Hosted Linux drove the running app and measured real PTYs across layout changes. | Local PTY holder timed out. Focus flash was outside scope. |
| [OpenCode #65284](https://github.com/anomalyco/opencode/pull/65284) | Local packaged macOS CLI upgrade over a throttled loopback server. Ran updater and pre-push checks. | Windows updater cases were skipped in that suite. |
| [OpenCode #65291](https://github.com/anomalyco/opencode/pull/65291) | Local real source server and TUI with a loopback model. Checked retained rows, active calls, and regressions. | Controlled model responses. |
| [OpenCode #65314](https://github.com/anomalyco/opencode/pull/65314) | Local built UI and real source server with a loopback model. Exercised queue, delivery, and Undo behavior. | Separate dev-server timeouts and an inconclusive hosted performance comparison were disclosed. |
| [Schemathesis #6198](https://github.com/schemathesis/schemathesis/pull/6198) | Local real `st run` and `st fuzz` against a loopback API. Checked conflicting and distinct report paths. | Broader snapshot failures reproduced on the base. |
| [Schemathesis #6199](https://github.com/schemathesis/schemathesis/pull/6199) | Local real CLI exercised the named baseline, update, and prune paths. | One-operation loopback API. |
| [Schemathesis #6200](https://github.com/schemathesis/schemathesis/pull/6200) | Local real CLI parsed generated JUnit XML and verified explicit-path overrides. Ran adjacent suites. | `/dev/full` skipped locally. |
| [act #6265](https://github.com/nektos/act/pull/6265) | Real pull executor checked both image spellings against a loopback Docker API. Hosted run verified the exact commits. | A loopback fixture verified the header; Docker Hub credentials and a real pull were outside scope. |
| [act #6266](https://github.com/nektos/act/pull/6266) | Local CLI ran malformed and valid composite workflows. Hosted regression checked the diagnosed cleanup path. | A wider macOS test failed the same way at the base. |
| [act #6267](https://github.com/nektos/act/pull/6267) | Local built CLI tested inherited empty values, explicit empty values, and missing values. Ran command suite. | The fixture uses the host executor. [Exact local gate receipt and logs](https://gist.github.com/archit15singh/0cfb2c3bcca37a10bab4fb6b9fa61dde). |
| [Promptfoo #12534](https://github.com/promptfoo/promptfoo/pull/12534) | Local real eval CLI checked configured and explicit output paths and parsed JSON. | Deterministic echo provider. |
| [Promptfoo #12535](https://github.com/promptfoo/promptfoo/pull/12535) | Local real eval/list CLI checked persistence precedence on the original head. | The maintainer added watched-default-config behavior after the PR description was written. |
| [Promptfoo #12536](https://github.com/promptfoo/promptfoo/pull/12536) | Local real CLI checked grader identity and relevant config/CLI tests. | Deterministic local graders. |
| [OpenHands SDK #7040](https://github.com/OpenHands/software-agent-sdk/pull/7040) | Local public editor API exercised delete, undo, and invalid insert. Ran editor suite. | Temp files and direct SDK calls. |
| [OpenHands SDK #7041](https://github.com/OpenHands/software-agent-sdk/pull/7041) | Local source audit checked docstrings against signatures and compared ASTs. | Docstring correction. The verification surface was source and documentation. |
| [OpenHands SDK #7047](https://github.com/OpenHands/software-agent-sdk/pull/7047) | Local real editor exercised create and edit on temp files and checked the diff renderer. | No paid model session was needed. |
| [Inspect AI #6699](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6699) | Ran the actual docs snippet against a repository dataframe fixture. Ran focused tests. | Repository samples and events. |
| [Inspect AI #6700](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6700) | Ran both docs snippets against the real cache policy and tool APIs. Ran default and Trio checks. | Targeted APIs and examples. |
| [Inspect AI #6701](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6701) | Ran the docs snippet through the real handoff registration API. | Provider-gated tests skipped. Model and web calls were outside scope. |

The existing receipts support focused verification, with different platforms and limits by PR. They do not establish a uniform local live run or documented review of adjacent scenarios for every PR. The new gate requires both for new submissions.
