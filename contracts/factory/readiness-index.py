"""Replay the real regression where readiness accepted --runs and left no record."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def run(case):
    with TemporaryDirectory(prefix="factory-readiness-index-") as directory:
        root = Path(directory)
        repo = root / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)

        def git(*argv):
            return subprocess.check_output(["git", "-c", "user.name=Replay",
                                            "-c", "user.email=replay@example.invalid", *argv],
                                           cwd=repo, text=True).strip()

        source = repo / "behavior.txt"
        source.write_text("old")
        git("add", "behavior.txt")
        git("commit", "-qm", "old behavior")
        base = git("rev-parse", "HEAD")
        source.write_text("new")
        git("add", "behavior.txt")
        git("commit", "-qm", "new behavior")
        head = git("rev-parse", "HEAD")
        contract = root / "contract.json"
        check = {"name": "Fixture is readable", "command": [sys.executable, "-c", "print('ready')"],
                 "contains": "ready"}
        probe = "from pathlib import Path; value=Path('behavior.txt').read_text(); print(value); raise SystemExit(value!='new')"
        contract.write_text(json.dumps({"base": base, "candidate": head, "allowed_paths": ["behavior.txt"],
            "regression_paths": [], "command": [sys.executable, "-c", probe],
            "before": {"exit": 1, "contains": "old"}, "after": {"exit": 0, "contains": "new"},
            "readiness": {"live_entrypoint": "Fixture file", "setup": check, "suite": check,
                "controls": [{**check, "kind": "normal"}, {**check, "kind": "boundary"}],
                "exclusions": {"failure": "Only valid files are included in the fixture."}}}))
        template = root / "pr.md"
        template.write_text("## Readiness replay")
        output, runs = root / "readiness", root / "runs"
        args = [sys.executable, "-m", "delivery", "upstream-prepare", "--repo", str(repo),
                "--contract", str(contract), "--template", str(template), "--output", str(output),
                "--evidence-url", "https://example.invalid/readiness"]
        if case == "indexed":
            args += ["--runs", str(runs)]
        # The synthetic fixture exercises the local CLI in a credential-free subprocess.
        # Normal hosted calls to upstream-prepare still hit its local-only gate.
        env = {"PATH": os.environ["PATH"], "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run(args, env=env, check=True)
        assert (output / "pr.md").is_file()
        indexed = list(runs.glob("*.json"))
        if case == "ordinary":
            assert not indexed
            print("ordinary readiness generated the PR packet")
            return 0
        if not indexed:
            print("readiness accepted the flag and omitted the record")
            return 1
        assert len(indexed) == 1
        receipt = json.loads(indexed[0].read_text())
        assert receipt["head"] == head and receipt["outcome"]["readiness"] == "verified"
        print("readiness indexed the exact candidate")
        return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
