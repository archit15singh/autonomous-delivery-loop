# Improving the factory reviewer

The loop learns from repository reviewers who approved a particular revision or asked for changes. It compares the factory’s current cold-review skill with a candidate on the same diffs. A passing experiment produces a patch for an operator to review and merge through Git. The next cold review reads the merged skill. Reverting the prompt commit rolls it back.

Run from the factory checkout with Git, an authenticated GitHub CLI, and an authenticated Codex CLI. Use a separate Git checkout of the project whose reviews you are studying. Its remotes must include the upstream project and its object database must contain the target base, PR tip, and reviewed commits. A full fetch and a fetch of the relevant pull refs may be necessary.

## Collect decisions

Choose the issue families and splits before drafting. Reserve independent PRs for holdout. Each split needs at least one approval and one request for changes to evaluate. Keep one repository per case directory. A review ID is the numeric suffix in its GitHub review permalink.

```sh
repo=/path/to/target-checkout
cases=.adl/reviewer/cases
candidate=.adl/reviewer/candidate.md

python3 -m delivery factory review-loop harvest \
  https://github.com/UKGovernmentBEIS/inspect_ai/pull/6701 6007787800 \
  --repo "$repo" --cases "$cases" --split development
```

Repeat for each decision. The harvester writes one immutable JSON file per PR, with the review URL, author, rationale, reviewed commit, merge base, verdict and any file locations on a request for changes. Archive the case files with the experiment. A later repair on the branch can follow the original reviewed revision. Ambiguous, dismissed, retargeted or unrecoverable reviews can be ineligible. GitHub association and current push access establish provenance. An unmarked account can still use automation, and an approved change can still have a bug. Inspect the evidence when selecting cases.

The first Inspect AI pilot used these four decisions. The holdout cases are reserved for evaluation. The two development PRs concern an invalidated sample during retry and a documented handoff example.

| Split | Approval | Changes requested |
| --- | --- | --- |
| Development | [#6701 · 6007787800](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6701#pullrequestreview-6007787800) | [#6652 · 5984485987](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6652#pullrequestreview-5984485987) |
| Holdout | [#6649 · 5981083262](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6649#pullrequestreview-5981083262) | [#6308 · 5936577281](https://github.com/UKGovernmentBEIS/inspect_ai/pull/6308#pullrequestreview-5936577281) |

## Run the loop

Once the case directory is ready, use one command for the full cycle.

```sh
python3 -m delivery factory review-loop run --repo "$repo" --cases "$cases"
```

The result names the run directory and its decision. A run can finish with no development disagreements, retain the baseline after comparison, or produce a patch awaiting operator review. Repeat the command after an interruption. The loop reuses the saved proposal and completed trial reports for the same cohort, model, prompts and round count. Keep the run directory outside the target repository when possible.

## Run the stages separately

```sh
python3 -m delivery factory review-loop propose \
  --repo "$repo" --cases "$cases" --candidate "$candidate"

python3 -m delivery factory --output .adl/reviewer/experiment.json review-loop evaluate \
  --repo "$repo" --cases "$cases" --candidate "$candidate" --cache .adl/reviewer/trials
```

The proposer runs the baseline on development cases. If it finds a disagreement it asks Codex to draft revised guidance using the development evidence. It leaves the candidate path empty when the decisions agree. An operator can also supply a candidate using the current skill’s front matter.

Evaluation defaults to three rounds. Each case gets a baseline and candidate review in each round using one model. Four cases cost 24 reviews at that setting, plus proposal work and separate judgments on disputed defects. The model sees the diff and reviewer guidance. The scorer sees the independent GitHub decision. Completed trials are written atomically and reused on retry with matching inputs.

A false alarm is a finding on an approved revision. A request for changes counts as a miss if the model approved it, missed a cited file, or failed to describe the blocking defect. A separate judge compares the report with the maintainer’s rationale without seeing which prompt produced it. Inspect the judge’s explanation alongside the raw findings before adopting a prompt. A mistaken reference decision or judge can still misgrade a review. With complete evidence, every round must preserve or improve both counts on each split and strictly reduce total holdout errors. A failed comparison returns status 1 and writes its evidence. A tie retains the current prompt.

## Promote

```sh
python3 -m delivery factory review-loop promotion-patch \
  --cases "$cases" --candidate "$candidate" --receipt .adl/reviewer/experiment.json \
  --patch .adl/reviewer/guidance.patch
git apply --check .adl/reviewer/guidance.patch
```

In a prompt-change branch, an operator reviews the raw paired results, applies the patch, and submits it for approval. The exporter recomputes the result from trial reports, checks the dataset and both prompt hashes, and writes a patch against the skill used by `cold-review`. Keep the evidence and cache in trusted storage. Digests detect drift and do not authenticate an operator-controlled file. After examining holdout failures, reserve new cases before using another experiment to claim generalization.

## Calibrate the judge

Run the production judge against reference answers before interpreting a reviewer experiment, especially after changing the rubric or model.

```sh
python3 -m delivery factory --output .adl/reviewer/calibration.json review-loop calibrate --rounds 2
```

The four frozen examples in [evals/review-judge.json](../evals/review-judge.json) cover paraphrases, another bug in the same file, and a review that catches only one of two defects. These are synthetic controls. Each round makes one fresh judge call per example. The judge sees the maintainer rationale and review findings. The scorer compares its response with the stored answer and records false matches, missed matches, and the judge’s explanation. The command returns status 1 for any disagreement. An incomplete or invalid run raises an error. Use the model name and the rubric and dataset digests in the receipt to identify the evaluated configuration. Passing these controls establishes performance on these examples only.

To evaluate a rubric change, first save a calibration receipt on `main`. Save a second receipt on the candidate branch with the same `--dataset`, `--model` and `--rounds` arguments. Check that the dataset digest, model name and round count agree. Pair the `results` records by `id` and `round` and inspect both reasons wherever `judgment.matched` changed. A lower error total can conceal a newly missed control. Include the paired comparison in the rubric PR for operator review.
