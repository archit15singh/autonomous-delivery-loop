# First upstream delivery batch

2026-11-20

I selected three points in the benchmark delivery chain where a focused change could be verified independently. Each upstream candidate was checked against an exact base commit and an explicit file allowlist. The upstream PRs contain the change and its evidence for maintainer review.

| Project | Change | Before and after |
| --- | --- | --- |
| [SWE-bench #726](https://github.com/SWE-bench/SWE-bench/pull/726) | Correct task-repository paths in the CLI help and README. | The old dataset example exited 2 on an unsupported option. A separate checkout at `a48b759` compiled `test.parquet` from the repository test fixture and passed 33 focused tests. The single Docker-backed integration test requires a daemon. |
| [SWE-bench task data #26](https://github.com/SWE-bench/swe-bench-tasks/pull/26) | Keep NumPy 1.x for the historical pvlib-1606 evaluator. | The official gold and test patches on CPython 3.9 failed during collection with NumPy 2.0.2. The exact command from `06b43c9` selected 1.26.4 and all 11 targeted tests passed, including the benchmark acceptance test. |
| [sb-cli #39](https://github.com/SWE-bench/sb-cli/pull/39) | Explain hosted report JSON and where to generate raw local evaluator logs. | The CLI wrote one or two JSON files against a loopback HTTP fixture, depending on the response. Neither case emitted raw logs. The changed guide at `eebdee5` built and rendered with MkDocs. |

## Reproduce the pvlib result

With Python 3.9 and Git, run the [pinned replay script](../verification/pvlib-1606.sh):

```sh
bash verification/pvlib-1606.sh
```

The [hosted workflow](../.github/workflows/upstream-evidence.yml) repeats the replay on Linux and uploads the failing and passing output. The experiment isolates the NumPy incompatibility and applies the real gold and test patches. Rebuilding or publishing the upstream image and dataset is part of the maintainers' release process.

For the other issues I screened, I deferred to existing review threads where an equivalent fix was already open. That included issues in OpenHands, pytest-xdist, tox, and Phoenix. The [ecosystem research](ecosystem.md) explains how those projects fit into the larger delivery loop.
