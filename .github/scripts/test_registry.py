import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from jsonschema import ValidationError

from allocate_identifiers import LABEL, STATE_BRANCH, STATE_FILE, allocation_request, prepare
from registry import LIST, SCHEMA, additions, reserve, validate, validate_reservations

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VALUE = json.loads((ROOT / SCHEMA).read_text())


def entry(alg="com.example.first", identifier=1):
    result = copy.deepcopy(SCHEMA_VALUE["examples"][0][0])
    result["alg"] = alg
    if identifier is None:
        result.pop("identifier")
    else:
        result["identifier"] = identifier
    return result


class RegistryTests(unittest.TestCase):
    def test_missing_id_only_allowed_for_new_submission(self):
        old = entry()
        proposed = [old, entry("com.example.new", None)]
        validate(proposed, SCHEMA_VALUE, [old], submission=True)
        with self.assertRaises(ValidationError):
            validate(proposed, SCHEMA_VALUE, [old])
        proposed[0].pop("identifier")
        with self.assertRaises(ValueError):
            validate(proposed, SCHEMA_VALUE, [entry()], submission=True)

    def test_published_identity_cannot_change(self):
        old = entry()
        for field, value in [("identifier", 4), ("alg", "com.example.renamed"), ("type", "fingerprint")]:
            changed = dict(old, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate([changed], SCHEMA_VALUE, [old], submission=True)
        # TWG removals remain possible; reserve() keeps the retired ID forever.
        validate([], SCHEMA_VALUE, [old])

    def test_duplicate_algs_and_ids_rejected(self):
        for proposed in [[entry(), entry()], [entry(), entry("com.example.other")]]:
            with self.assertRaises(ValueError):
                validate(proposed, SCHEMA_VALUE, submission=True)

    def test_submission_still_checks_fields_and_formats(self):
        for field, value in [("type", "unknown"), ("identifier", -1)]:
            with self.assertRaises(ValidationError):
                validate([dict(entry(), **{field: value})], SCHEMA_VALUE, submission=True)
        bad = entry(identifier=None)
        bad["entryMetadata"]["contact"] = "invalid"
        with self.assertRaises(ValidationError):
            validate([bad], SCHEMA_VALUE, submission=True)

    def test_allocation_is_idempotent_and_replaces_legacy_ids(self):
        original = [entry("com.example.second", 1), entry("com.example.third", None)]
        ledger, allocated = reserve({}, [entry()], original, 10)
        self.assertEqual([e["identifier"] for e in allocated], [2, 3])
        self.assertEqual(reserve(ledger, [entry()], original, 10), (ledger, allocated))
        self.assertEqual(original[0]["identifier"], 1)
        self.assertNotIn("identifier", original[1])

    def test_reservations_survive_abandoned_prs_and_removed_entries(self):
        ledger, _ = reserve({}, [entry()], [entry("com.example.second", None)], 10)
        ledger, allocated = reserve(ledger, [], [entry("com.example.third", None)], 11)
        self.assertEqual(allocated[0]["identifier"], 3)
        self.assertEqual(ledger["algorithms"]["com.example.first"]["identifier"], 1)
        with self.assertRaises(ValueError):
            reserve(ledger, [], [entry("com.example.second", None)], 12)

    def test_manual_publication_cannot_take_a_reserved_id(self):
        ledger, _ = reserve({}, [entry()], [entry("com.example.second", None)], 10)
        with self.assertRaises(ValueError):
            reserve(ledger, [entry(), entry("com.example.interloper", 2)], [], 11)

    def test_space_exhaustion_and_corrupt_ledger_fail_closed(self):
        with self.assertRaises(ValueError):
            reserve({}, [entry(identifier=65535)], [entry("com.example.new", None)], 10)
        with self.assertRaises(ValueError):
            reserve({"algorithms": {"a": {"identifier": 1}, "b": {"identifier": 1}}}, [], [], 10)

    def test_only_new_entries_are_copied(self):
        old, new = entry(), entry("com.example.new", None)
        self.assertEqual(additions([old], [old, new]), [new])
        with self.assertRaises(ValueError):
            additions([old], [dict(old, type="fingerprint"), new])
        with self.assertRaises(ValueError):
            additions([old], [old])

    def test_new_published_entries_require_matching_reservations(self):
        old, new = entry(), entry("com.example.new", 2)
        with self.assertRaisesRegex(ValueError, "No reserved"):
            validate_reservations([old, new], [old], {})
        ledger, allocated = reserve({}, [old], [new], 10)
        validate_reservations([old] + allocated, [old], ledger)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_reservations([old, dict(new, identifier=3)], [old], ledger)


class FakeGitHub:
    """In-memory API: exercises orchestration without any live mutations."""
    repo = "owner/registry"

    def __init__(self):
        self.published = [entry()]
        self.proposed = self.published + [entry("com.example.new", None)]
        self.pr = {"number": 10, "state": "open", "base": {"ref": "main", "sha": "main1"},
                   "head": {"sha": "a" * 40}, "labels": [{"name": LABEL}], "changed_files": 1,
                   "html_url": "https://github.com/owner/registry/pull/10", "user": {"login": "contributor"}}
        self.refs = {"main": "main1"}
        self.contents = {"main1": {LIST: self.published, SCHEMA: SCHEMA_VALUE}}
        self.integrations = []
        self.comments = []
        self.dispatches = []
        self.permission = "write"
        self.conflict_once = False
        self.commit_count = 0
        self.withdraw_after_reserving = False

    def get(self, path):
        result = self.optional(path)
        if result is None:
            raise AssertionError(f"Unexpected GET {path}")
        return copy.deepcopy(result)

    def optional(self, path):
        if path.startswith("collaborators/"):
            return {"permission": self.permission}
        if path == "pulls/10":
            if self.withdraw_after_reserving and STATE_BRANCH in self.refs:
                self.pr["labels"] = []
            return copy.deepcopy(self.pr)
        if path.startswith("pulls/10/files"):
            return [{"filename": LIST}]
        if path.startswith("compare/"):
            return {"merge_base_commit": {"sha": "base"}}
        if path.startswith("git/ref/heads/"):
            name = path.removeprefix("git/ref/heads/")
            return {"object": {"sha": self.refs[name]}} if name in self.refs else None
        if path.startswith("git/commits/"):
            return {"tree": {"sha": "main-tree"}}
        if path.startswith("pulls?"):
            return self.integrations
        if path.startswith("issues/10/comments?"):
            return self.comments
        raise AssertionError(f"Unexpected GET {path}")

    def content(self, path, ref):
        if ref == "base":
            return copy.deepcopy(self.published)
        if ref == "a" * 40:
            return copy.deepcopy(self.proposed)
        return copy.deepcopy(self.contents[ref][path])

    def commit_file(self, path, value, parent, message, base_tree=None):
        self.commit_count += 1
        sha = f"commit{self.commit_count}"
        self.contents[sha] = {path: copy.deepcopy(value)}
        return sha

    def call(self, method, path, data):
        if path == "git/refs":
            name = data["ref"].removeprefix("refs/heads/")
            if self.conflict_once and name == STATE_BRANCH:
                self.conflict_once = False
                ledger, _ = reserve({}, self.published, [entry("com.example.other", None)], 99)
                self.contents["concurrent"] = {STATE_FILE: ledger}
                self.refs[STATE_BRANCH] = "concurrent"
                raise HTTPError("test", 422, "Reference already exists", {}, io.BytesIO())
            if name in self.refs:
                raise AssertionError("Duplicate branch")
            self.refs[name] = data["sha"]
        elif path.startswith("git/refs/heads/"):
            assert data["force"] is False
            self.refs[path.removeprefix("git/refs/heads/")] = data["sha"]
        elif path == "pulls":
            pr = dict(data, number=11, state="open", html_url="https://github.com/owner/registry/pull/11")
            self.integrations.append(pr)
            return pr
        elif path.endswith("/dispatches"):
            self.dispatches.append(data)
        elif path == "issues/10/comments":
            self.comments.append(dict(data, id=20, user={"login": "github-actions[bot]"}))
        elif path == "issues/comments/20":
            self.comments[0].update(data)
        else:
            raise AssertionError(f"Unexpected {method} {path}")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request_target", "GITHUB_ACTOR": "maintainer"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.api = FakeGitHub()
        self.event = {"action": "labeled", "label": {"name": LABEL},
                      "pull_request": copy.deepcopy(self.api.pr), "repository": {"default_branch": "main"}}

    def test_end_to_end_and_retry_do_not_duplicate_pr_or_comment(self):
        prepare(self.api, self.event)
        prepare(self.api, self.event)
        self.assertEqual(len(self.api.integrations), 1)
        self.assertEqual(len(self.api.comments), 1)
        prepared = self.api.content(LIST, self.api.refs["bot/register-pr-10-aaaaaaaaaaaa"])
        self.assertEqual(prepared[-1]["identifier"], 2)
        self.assertEqual(prepared[0], self.api.published[0])
        self.assertEqual(self.api.refs["main"], "main1")
        self.assertEqual(len(self.api.dispatches), 2)

    def test_concurrent_allocator_retries_without_duplicate_id(self):
        self.api.conflict_once = True
        prepare(self.api, self.event)
        prepared = self.api.content(LIST, self.api.refs["bot/register-pr-10-aaaaaaaaaaaa"])
        self.assertEqual(prepared[-1]["identifier"], 3)

    def test_nonmaintainer_cannot_trigger_allocation(self):
        self.api.permission = "read"
        with self.assertRaisesRegex(ValueError, "Only maintainers"):
            prepare(self.api, self.event)
        self.assertEqual(self.api.refs, {"main": "main1"})

    def test_source_changed_after_labeling_is_rejected(self):
        self.api.pr["head"]["sha"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "Source changed"):
            prepare(self.api, self.event)

    def test_code_changes_are_not_copied(self):
        self.api.pr["changed_files"] = 2
        with self.assertRaisesRegex(ValueError, "must change only"):
            prepare(self.api, self.event)

    def test_wrong_base_or_withdrawn_request_is_rejected(self):
        for change in [lambda: self.api.pr.update(labels=[]),
                       lambda: self.api.pr["base"].update(ref="develop"),
                       lambda: self.api.pr.update(state="closed")]:
            self.api = FakeGitHub()
            change()
            with self.assertRaises(ValueError):
                allocation_request(self.api, self.event)

    def test_manual_retry_requires_current_label_and_maintainer(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}):
            event = dict(self.event, inputs={"pr_number": "10"})
            prepare(self.api, event)
            self.api.pr["labels"] = []
            with self.assertRaises(ValueError):
                prepare(self.api, event)

    def test_modified_prepared_branch_is_never_overwritten(self):
        prepare(self.api, self.event)
        sha = self.api.refs["bot/register-pr-10-aaaaaaaaaaaa"]
        self.api.contents[sha][LIST][-1]["entryMetadata"]["description"] = "Maintainer edit"
        with self.assertRaisesRegex(ValueError, "differs"):
            prepare(self.api, self.event)

    def test_withdrawal_after_reservation_keeps_id_without_opening_pr(self):
        self.api.withdraw_after_reserving = True
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            prepare(self.api, self.event)
        self.assertIn(STATE_BRANCH, self.api.refs)
        self.assertFalse(self.api.integrations)

    def test_non_fast_forward_conflict_retries_from_winning_ledger(self):
        from allocate_identifiers import persist_reservations
        prepare(self.api, self.event)
        original_call = self.api.call
        conflict = True

        def competing_update(method, path, data):
            nonlocal conflict
            if method == "PATCH" and path == f"git/refs/heads/{STATE_BRANCH}" and conflict:
                conflict = False
                ref = self.api.refs[STATE_BRANCH]
                ledger = self.api.contents[ref][STATE_FILE]
                ledger, _ = reserve(ledger, self.api.published, [entry("com.example.competing", None)], 99)
                self.api.contents["winner"] = {STATE_FILE: ledger}
                self.api.refs[STATE_BRANCH] = "winner"
                raise HTTPError("test", 422, "Not a fast forward", {}, io.BytesIO())
            return original_call(method, path, data)

        self.api.call = competing_update
        _, _, _, allocated = persist_reservations(self.api, "main", [entry("com.example.next", None)], 12)
        self.assertEqual(allocated[0]["identifier"], 4)

    def test_closed_prepared_pr_is_not_duplicated(self):
        prepare(self.api, self.event)
        self.api.integrations[0]["state"] = "closed"
        with self.assertRaisesRegex(ValueError, "prepared PR is closed"):
            prepare(self.api, self.event)
        self.assertEqual(len(self.api.integrations), 1)


if __name__ == "__main__":
    unittest.main()
