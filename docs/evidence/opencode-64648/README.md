# OpenCode #64648 prompt Undo replay

| Revision | SHA |
| --- | --- |
| Base | `b83ea513658eed65291d218d2363fc91c09a2141` |
| Candidate | `00dde43a8362ffe4fc2df38cdcf8c936fc83dcfa` |

Both live API runs use the real source server on macOS with Bun 1.4.4, a new
temporary project and a loopback fixture model. Run from the checkout root
with dependencies installed and save `replay.py` outside the checkout.

```sh
python3 /path/to/replay.py . "$(command -v bun)" cancel-only  # base
python3 /path/to/replay.py . "$(command -v bun)" rewind      # candidate
```

The replay sends the ordered HTTP calls of each app path. DELETE returns 204
for both successful cancellation and a stale inbox item. With the stale item
and no rewind, sending again leaves two prompts and two replies. After staging
rewind, resending leaves one prompt and one reply, and the model receives one
copy. The browser tests separately drive the actual composer with its upstream
Playwright fixture.

| Queue Undo at base | Queue Undo at candidate |
| --- | --- |
| ![The delivered prompt was appended to the current draft](browser-before.png) | ![The current draft is preserved](browser-after.png) |

Both new cases fail on the base with only the test file overlaid. [Base test output](browser-base-overlay.log)

The built app passed all 50 tests in `session-queue.spec.ts` using headless
Brave with the upstream test config. The [local config](adl-playwright.config.ts)
adds the executable path and enables screenshots. [Candidate test output](browser-candidate.log)

```sh
cd packages/app
cp /path/to/adl-playwright.config.ts .adl-playwright.config.ts
PLAYWRIGHT_BUILD=1 PLAYWRIGHT_PORT=4378 bun run test:e2e -- \
  --config .adl-playwright.config.ts --workers 1 --reporter line \
  e2e/regression/session-queue.spec.ts
```

At the repository root, `bun run check` passed all 35 tasks. The standalone
`typecheck:e2e` command has identical diagnostics at base and candidate,
including stylesheet declarations outside the changed files.
