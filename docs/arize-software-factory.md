# What ADL can learn from the Arize software factory

Research checked November 22, 2026. Jim Bennett's factory makes a review decision reproducible. It saves the code revision a reviewer originally saw, the prompt version it used, its finding, and the first subsequent gate verdict. That lets an operator ask whether a different prompt would have made a better decision with the information available at the time. [Reference implementation at c3db3d9](https://github.com/jimbobbennett/software-factory/tree/c3db3d95394d888997dc2abbd9bb11b896760b02)

## How the evidence is produced

Claude agents specify, implement, repair and review changes to the ship-it-card application. Python performs GitHub writes. The router records its own recommendation and the decision after fixed rules are applied. Arize AX connects the decisions and prompt versions to a trace for the issue. The author describes a human review gate. Its first verdict is comparable to the initial review because subsequent fixes return directly to the gate. A gate label identifies a decision and its rationale. The stored example alone does not identify the individual who made that judgment. The repository also ships a simulator that generates dashboard events. [Factory workflow](https://github.com/jimbobbennett/software-factory/blob/c3db3d95394d888997dc2abbd9bb11b896760b02/README.md) · [Example label](https://github.com/jimbobbennett/software-factory/blob/c3db3d95394d888997dc2abbd9bb11b896760b02/labels/gate/15.json) · [Simulator](https://github.com/jimbobbennett/software-factory/blob/c3db3d95394d888997dc2abbd9bb11b896760b02/factory/simulate.py)

## What improved

| Author-reported experiment | Result | Interpretation |
| --- | --- | --- |
| Correctness reviewer, 19 historical PRs, three repetitions per prompt | Baseline missed 2, 3 and 2. The candidate missed zero each time with zero false alarms. | The optimizer had seen these failures. Repetition measures run variability on those same cases. |
| Eight planted bugs and five clean controls, three repetitions | Both prompts caught all eight and cleared all five every time. | This control could detect a regression but supplied no evidence of an advantage on unseen bugs. |
| Router, 17 PRs, three repetitions | Unnecessary escalations fell from nine to six. Both recorded zero unsafe routes. | These are historical routing decisions scored against gate verdicts. Actual review hours saved and production incidents require separate measurement. |

The gate itself was wrong on two later cases, according to Bennett. An erroneous gate label can reward an erroneous reviewer. [Experiment and subsequent cases](https://arize.com/blog/how-to-build-a-software-factory-that-tests-its-own-prompts/)

The code adds a further caveat. The reviewer tally records how many runs received a judgment. Its promotion predicate compares mean counts of misses and false alarms without requiring a judgment for every expected example. A missing judgment can lower a count. This is a possible failure mode in reuse, not a finding that Bennett's published runs were incomplete. [Reviewer tally and gate](https://github.com/jimbobbennett/software-factory/blob/c3db3d95394d888997dc2abbd9bb11b896760b02/factory/experiment.py#L253-L280) · [Promotion predicate](https://github.com/jimbobbennett/software-factory/blob/c3db3d95394d888997dc2abbd9bb11b896760b02/factory/experiment.py#L367-L392)

## Smallest useful ADL experiment

ADL already replays old and new guidance against a rejected finding and a second, held-out revision with a known valid finding. It requires that the false positive disappear while both reviewers retain the control finding at the expected path. Its delivery score separately tracks milestones such as verification and merge. A merge can show a contribution landed. It cannot by itself tell us whether an earlier review finding was correct. [Existing replay](../delivery/factory_feedback.py) · [Delivery score](../delivery/factory_score.py)

The [ADL implementation](reviewer-improvement.md) freezes one JSON record per PR, including the review link and the revisions under comparison. The case directory serves as a versioned dataset through its digest and can be archived or committed separately. A development pass proposes reviewer instructions. A separate judge checks whether a finding describes the defect in the maintainer’s rationale. Repeated paired trials measure false alarms and misses on both splits, and an operator can export a passing prompt as a Git patch. Operators choose independent PR families and audit the underlying labels.

## Other sources in the material

- Phoenix offers self-hosted tracing, versioned datasets, experiments, prompt management and an MCP endpoint. It becomes useful when comparing traces across runs takes substantial manual work. Its Elastic License 2.0 restricts third-party hosted offerings exposing substantial Phoenix functionality. Bennett's factory separately uses the MIT license. [Phoenix](https://github.com/Arize-ai/phoenix) · [Phoenix license](https://github.com/Arize-ai/phoenix/blob/main/LICENSE) · [Factory license](https://github.com/jimbobbennett/software-factory/blob/c3db3d95394d888997dc2abbd9bb11b896760b02/LICENSE)
- Factory cofounder Eno Reyes's Observe talk puts the focus on deterministic tests, cycle time, escaped bugs and incidents. These are outcome measures ADL can track after changing a reviewer. [Agent readiness](https://www.youtube.com/watch?v=SkoT4RkteSA&t=620s) · [Outcome measures](https://www.youtube.com/watch?v=SkoT4RkteSA&t=763s)
- The pictured OpenAI cookbook notebook is a separate, archived prompt-optimization example. It uses a static stream of document sections, multiple graders and bounded retries. It offers a pattern for combining deterministic checks with judgment. Its experiment concerns summarization. [OpenAI cookbook](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining)
