"""Independent behavior probes for the workflow HEAD drift incident."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path.cwd()))
from delivery.factory_workflow import workflow


def run(case):
    with TemporaryDirectory(prefix="factory-identity-replay-") as directory:
        root = Path(directory)
        repo = root / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        commit = ["git", "-c", "user.name=Replay", "-c", "user.email=replay@example.invalid",
                  "commit", "--allow-empty", "--quiet", "-m"]
        subprocess.run([*commit, "reviewed"], cwd=repo, check=True)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        verify = {"id": "verify", "kind": "command", "argv": [sys.executable, "-c", "print('ok')"]}
        steps = ([{"id": "change", "kind": "command", "argv": [*commit, "new revision"]}, verify]
                 if case == "drift" else [verify, {"id": "review", "kind": "approval"}])
        plan = root / "plan.json"
        plan.write_text(json.dumps({"version": 1, "revision": revision, "steps": steps}))
        state = root / "state"
        result = workflow(plan, repo, state, "full")
        if case == "drift":
            blocked = result["status"] == "failed" and "verify" not in result["steps"]
            print("blocked a clean HEAD change" if blocked else "verified a different HEAD")
            return int(not blocked)
        assert result["status"] == "waiting_for_approval"
        final = workflow(plan, repo, state, "full", result["approval_request"])
        assert final["status"] == "verified" and final["steps"]["verify"]["attempt"] == 1
        print("approval resumes the same verified step")
        return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
