"""Reserve identifiers and open a data-only integration PR using GitHub's API.

This script must be run from the trusted default branch, never from a fork.
No proposed code, workflow, schema, or git hooks are executed.
"""

import base64
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from registry import LIST, SCHEMA, additions, reserve, validate

STATE_BRANCH = "bot/identifier-allocations"
STATE_FILE = "identifier-allocations.json"
LABEL = "ready-to-register"


class GitHub:
    def __init__(self):
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.root = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        self.token = os.environ["GH_TOKEN"]

    def call(self, method, path, data=None):
        request = Request(
            f"{self.root}/repos/{self.repo}/{path}",
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        with urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else None

    def get(self, path):
        return self.call("GET", path)

    def optional(self, path):
        try:
            return self.get(path)
        except HTTPError as error:
            if error.code == 404:
                return None
            raise

    def content(self, path, ref):
        result = self.get(f"contents/{quote(path, safe='/')}?{urlencode({'ref': ref})}")
        return json.loads(base64.b64decode(result["content"]))

    def commit_file(self, path, value, parent, message, base_tree=None):
        blob = self.call("POST", "git/blobs", {
            "content": json.dumps(value, indent=4, ensure_ascii=False) + "\n", "encoding": "utf-8"})
        tree = {"tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}]}
        if base_tree:
            tree["base_tree"] = base_tree
            # Preserve executable mode of the existing list, if present.
            current = self.get(f"git/trees/{base_tree}")
            for item in current["tree"]:
                if item["path"] == path:
                    tree["tree"][0]["mode"] = item["mode"]
        tree = self.call("POST", "git/trees", tree)
        return self.call("POST", "git/commits", {
            "message": message, "tree": tree["sha"], "parents": [parent]})["sha"]


def allocation_request(api, event):
    """Check both who requested allocation and the exact reviewed PR snapshot."""
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request_target":
        if event.get("action") != "labeled" or event["label"]["name"] != LABEL:
            raise ValueError("Expected the ready-to-register label event")
        number = event["pull_request"]["number"]
        expected_head = event["pull_request"]["head"]["sha"]
    else:
        number = int(event["inputs"]["pr_number"])
        expected_head = None
    if number < 1:
        raise ValueError("Invalid PR number")
    actor = os.environ["GITHUB_ACTOR"]
    permission = api.get(f"collaborators/{quote(actor, safe='')}/permission")["permission"]
    if permission not in ("admin", "maintain", "write"):
        raise ValueError("Only maintainers with write permission can request allocation")
    pr = api.get(f"pulls/{number}")
    default = event["repository"]["default_branch"]
    if pr["state"] != "open" or pr["base"]["ref"] != default:
        raise ValueError("Source PR must be open and target the default branch")
    if LABEL not in [label["name"] for label in pr["labels"]]:
        raise ValueError("Source PR no longer has the ready-to-register label")
    if expected_head and pr["head"]["sha"] != expected_head:
        raise ValueError("Source changed after labeling; review it and reapply the label")
    files = api.get(f"pulls/{number}/files?per_page=100")
    if pr["changed_files"] != 1 or len(files) != 1 or files[0]["filename"] != LIST:
        raise ValueError(f"Allocation PRs must change only {LIST}")
    return pr


def persist_reservations(api, default, entries, source_pr):
    """The non-force ref update is the lock: competing writers retry from state.

    A workflow concurrency group reduces collisions, but correctness does not
    rely on GitHub scheduling or on an uninterrupted workflow run.
    """
    for _ in range(8):
        main_sha = api.get(f"git/ref/heads/{quote(default, safe='')}")["object"]["sha"]
        published = api.content(LIST, main_sha)
        schema = api.content(SCHEMA, main_sha)
        state = api.optional(f"git/ref/heads/{STATE_BRANCH}")
        state_sha = state["object"]["sha"] if state else None
        ledger = api.content(STATE_FILE, state_sha) if state else {}
        updated, allocated = reserve(ledger, published, entries, source_pr)
        validate(published + allocated, schema, published)
        if updated == ledger:
            return main_sha, published, schema, allocated
        sha = api.commit_file(STATE_FILE, updated, state_sha or main_sha,
                              f"Reserve identifiers for PR #{source_pr}")
        try:
            if state:
                api.call("PATCH", f"git/refs/heads/{STATE_BRANCH}", {"sha": sha, "force": False})
            else:
                api.call("POST", "git/refs", {"ref": f"refs/heads/{STATE_BRANCH}", "sha": sha})
        except HTTPError as error:
            if error.code in (409, 422):
                continue
            raise
        return main_sha, published, schema, allocated
    raise ValueError("Concurrent allocation did not settle; rerun the workflow")


def prepare(api, event):
    pr = allocation_request(api, event)
    number, head = pr["number"], pr["head"]["sha"]
    default = event["repository"]["default_branch"]
    comparison = api.get(f"compare/{quote(default, safe='')}...{head}")
    base_sha = comparison["merge_base_commit"]["sha"]
    base = api.content(LIST, base_sha)
    proposed = api.content(LIST, head)
    # Validate with trusted schema, never one supplied by a contributor.
    schema = api.content(SCHEMA, pr["base"]["sha"])
    validate(proposed, schema, base, submission=True)
    new_entries = additions(base, proposed)
    main_sha, published, schema, allocated = persist_reservations(api, default, new_entries, number)
    final = published + allocated
    validate(final, schema, published)
    # Do not silently consume a different source revision during API requests.
    current = api.get(f"pulls/{number}")
    if current["head"]["sha"] != head or current["state"] != "open" or LABEL not in [x["name"] for x in current["labels"]]:
        raise ValueError("Source PR changed or was withdrawn; reservations are retained; review and rerun")
    branch = f"bot/register-pr-{number}-{head[:12]}"
    existing = api.optional(f"git/ref/heads/{branch}")
    if not existing:
        tree = api.get(f"git/commits/{main_sha}")["tree"]["sha"]
        sha = api.commit_file(LIST, final, main_sha,
                              f"Register algorithms from PR #{number}\n\nSource-PR: {pr['html_url']}\nSource-Commit: {head}", tree)
        api.call("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
    else:
        # Never overwrite a maintainer's changes or rewrite a reviewed branch.
        sha = existing["object"]["sha"]
        actual = api.content(LIST, sha)
        validate(actual, schema, published)
        if actual != final:
            raise ValueError("Prepared branch differs from the current list; rebase/review it manually")
    rows = "\n".join(f"| `{e['alg']}` | {e['identifier']} |" for e in allocated)
    body = (f"Registers the new algorithms submitted by @{pr['user']['login']} in #{number}, "
            f"with automatically reserved identifiers.\n\nSource commit: `{head}`\n\n"
            "| Algorithm | Identifier |\n| --- | --- |\n" + rows +
            "\n\nOnly the algorithm list is copied onto the default branch. "
            "Please complete normal technical review and merge this PR instead of the source PR. "
            "After merging, close the source PR with a link to this registration. "
            "This is a snapshot: later source changes need renewed review and allocation. "
            "Reserved identifiers are never recycled.\n")
    owner = api.repo.split('/')[0]
    matches = api.get("pulls?" + urlencode({"state": "all", "head": f"{owner}:{branch}", "base": default}))
    if matches:
        integration = matches[0]
        if integration["state"] != "open":
            raise ValueError("The prepared PR is closed; reservations remain; reopen it for another attempt")
    else:
        integration = api.call("POST", "pulls", {
            "title": f"Register algorithms from #{number} with assigned identifiers",
            "body": body, "head": branch, "base": default})
    # GITHUB_TOKEN-generated events may need approval or not trigger CI. An
    # explicit workflow_dispatch reliably starts the normal read-only checks.
    api.call("POST", "actions/workflows/validate-json.yaml/dispatches", {"ref": branch})
    marker = "<!-- sbr-identifier-allocation -->"
    message = (f"{marker}\nPrepared registration: {integration['html_url']}\n\n"
               f"Reviewed source: `{head}`\n\n| Algorithm | Identifier |\n| --- | --- |\n{rows}\n\n"
               "Merge the prepared registration after review, then close this source PR. "
               "Do not merge this submission with missing or provisional identifiers.")
    # Idempotent notification, including pagination on long discussions.
    page = 1
    while True:
        comments = api.get(f"issues/{number}/comments?per_page=100&page={page}")
        own = next((c for c in comments if c["body"].startswith(marker)
                    and c["user"]["login"] == "github-actions[bot]"), None)
        if own:
            api.call("PATCH", f"issues/comments/{own['id']}", {"body": message})
            break
        if len(comments) < 100:
            api.call("POST", f"issues/{number}/comments", {"body": message})
            break
        page += 1
    print(integration["html_url"])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(message.replace(marker, "") + "\n")


if __name__ == "__main__":
    with open(os.environ["GITHUB_EVENT_PATH"]) as source:
        prepare(GitHub(), json.load(source))
