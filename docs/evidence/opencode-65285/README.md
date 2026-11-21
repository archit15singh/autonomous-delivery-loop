# OpenCode #65291 review replay

The replay runs the real server and TUI from source. A local fixture model asks Code Mode to fetch a loopback endpoint 260 times. The verifier reads the saved message from the API and opens it in the TUI at Low and High verbosity. The [original replay](https://gist.github.com/archit15singh/896fac843e7792d2e78640650ab1bcb9) compares the uncapped upstream base.

| Source commit | Calls executed | Rows saved | API message page | Low | High |
| --- | ---: | ---: | ---: | --- | --- |
| 9e96640ebbcbdeb520f8202356109de24d194388 | 260 | 128 | 14,599 B | 128 tools | 128 visible rows |
| 902d4b20a1e843b959efdd61003bd22afa8dad67 | 260 | 128 | 14,599 B | 260 tools | 132 calls omitted |

The images are rendered from the real PTY output. The High images are cropped to the first thirteen terminal lines.

From either source checkout, install locked dependencies using Bun 1.4.4. The capture skill supplies the Python environment with pyte and Pillow, the PTY sizing helper, and the PNG renderer.

```sh
bun install --frozen-lockfile
CAP="$HOME/.codex/skills/opencode-tui-capture"
"$CAP/.venv/bin/python" /path/to/replay.py "$PWD" "$(command -v bun)" ./replay-output "$CAP"
(cd packages/core && bun test --timeout 30000 test/tool-execute.test.ts test/tool-registry.test.ts test/codemode.test.ts)
(cd packages/tui && bun test --timeout 30000 test/cli/tui/session-verbosity.test.ts test/cli/tui/inline-tool-wrap-snapshot.test.tsx)
bun run check
```

On the reviewed candidate, 96 core tests and 30 TUI tests passed. The core test holds a call open through 140 finished calls before allowing it to settle. The full workspace check passed all 35 typecheck tasks.
