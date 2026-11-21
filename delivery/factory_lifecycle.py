"""Read lifecycle observations without treating hosting metadata as runtime proof."""
from datetime import datetime
import json
import re
import subprocess
from urllib.parse import quote

from .candidate import FULL_REVISION, git
from .upstream_ci import gh_json


REPOSITORY = re.compile(r"[\w.-]+/[\w.-]+", re.ASCII)
REVERT = re.compile(r"^This reverts commit ([a-f0-9]{40})\.$", re.MULTILINE)


def github_events(repository, environment, limit):
    if not REPOSITORY.fullmatch(repository) or not environment or not 1 <= limit <= 50:
        raise ValueError("provide owner/repo, an environment and a limit of 1–50")
    api = f"repos/{repository}"
    deployments = gh_json("api", f"{api}/deployments", "--method", "GET",
                          "-f", f"environment={environment}", "-F", f"per_page={limit}")
    releases = gh_json("api", f"{api}/releases?per_page={limit}")
    result = {"repository": repository, "environment": environment, "deployments": [], "events": []}
    for deployment in deployments:
        revision = deployment["sha"]
        if not FULL_REVISION.fullmatch(revision) or deployment["environment"] != environment:
            continue
        status = gh_json("api", f"{api}/deployments/{deployment['id']}/statuses?per_page=1")
        latest = status[0] if status else None
        result["deployments"].append({"id": str(deployment["id"]), "revision": revision,
                                     "reported_state": latest["state"] if latest else "unknown",
                                     "at": latest["created_at"] if latest else deployment["created_at"],
                                     "runtime_verdict": "inconclusive"})
    for release in releases:
        if release["draft"] or not release.get("published_at"):
            continue
        tag = release["tag_name"]
        revision = gh_json("api", f"{api}/commits/{quote(tag, safe='')}")["sha"]
        if FULL_REVISION.fullmatch(revision):
            result["events"].append({"subject": f"{repository}@{tag}", "event": "released",
                                     "revision": revision, "at": release["published_at"],
                                     "immutable": release.get("immutable") is True,
                                     "url": release["html_url"]})
    return result


def revert_events(repo, first, last):
    if not all(FULL_REVISION.fullmatch(ref) for ref in (first, last)):
        raise ValueError("revert scan requires two full Git revisions")
    git("merge-base", "--is-ancestor", first, last, cwd=repo)
    fields = git("log", "--first-parent", "--max-count=1000", "--format=%H%x00%cI%x00%B", "-z",
                 f"{first}..{last}", cwd=repo).decode().rstrip("\0").split("\0")
    events = []
    for revision, at, body in zip(fields[0::3], fields[1::3], fields[2::3]):
        target = REVERT.search(body)
        if (target and body.startswith("Revert ") and FULL_REVISION.fullmatch(revision)
                and datetime.fromisoformat(at).utcoffset() is not None):
            events.append({"subject": target[1], "revision": revision, "at": at,
                           "event": "reverted", "evidence": "git_revert_message"})
    return events


def read_analysis_run(context, namespace, name):
    if (not context or not namespace or not name or any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,252}", value)
        for value in (context, namespace, name)
    )):
        raise ValueError("select an explicit Kubernetes context, namespace and AnalysisRun")
    data = subprocess.check_output(["kubectl", f"--context={context}", f"--namespace={namespace}",
                                    "get", "analysisruns.argoproj.io", name,
                                    "--output=json", "--request-timeout=15s"], timeout=20)
    return json.loads(data)
