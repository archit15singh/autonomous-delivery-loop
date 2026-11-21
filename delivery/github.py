"""Shared GitHub repository identities and bounded JSON reads through gh."""
import json
import re
import subprocess


OWNER_REPO = "archit15singh/autonomous-delivery-loop"
PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/([1-9][0-9]*)", re.ASCII)


# A scan can report a missing GitHub observation and continue with other targets.
LOOKUP_ERRORS = (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError)


def gh_json(*args):
    return json.loads(subprocess.check_output(
        ["gh", *args], text=True, stdin=subprocess.DEVNULL, timeout=30,
    ))
