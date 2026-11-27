import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import ValidationError

from registry import LIST, SCHEMA, assign_identifiers, validate

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
        # TWG removals remain possible.
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

    def test_assignment_replaces_provisional_ids_without_mutating_input(self):
        old = entry(identifier=7)
        proposed = [old, entry("com.example.second", 7), entry("com.example.third", None)]
        assigned = assign_identifiers(proposed, [old])
        self.assertEqual([e["identifier"] for e in assigned], [7, 8, 9])
        self.assertEqual(assigned[0], old)
        self.assertEqual(proposed[1]["identifier"], 7)
        self.assertNotIn("identifier", proposed[2])
        validate(assigned, SCHEMA_VALUE, [old])
        self.assertEqual(assign_identifiers(assigned, [old]), assigned)

    def test_assignment_uses_maximum_in_unsorted_base(self):
        published = [entry(identifier=10), entry("com.example.second", 2)]
        assigned = assign_identifiers(published + [entry("com.example.new", None)], published)
        self.assertEqual(assigned[-1]["identifier"], 11)

    def test_assignment_from_empty_list(self):
        assigned = assign_identifiers([entry(identifier=None)], [])
        self.assertEqual(assigned[0]["identifier"], 0)

    def test_identifier_limit(self):
        published = [entry(identifier=65534)]
        assigned = assign_identifiers(published + [entry("com.example.last", None)], published)
        self.assertEqual(assigned[-1]["identifier"], 65535)
        with self.assertRaisesRegex(ValueError, "exhausted"):
            assign_identifiers(assigned + [entry("com.example.extra", None)], published)

    def test_assignment_recalculates_after_another_registration_merges(self):
        old = entry()
        pending = [old, entry("com.example.pending", 2)]
        published = [old, entry("com.example.merged", 2)]
        proposed = published + pending[1:]
        with self.assertRaisesRegex(ValueError, "Duplicate identifier"):
            validate(proposed, SCHEMA_VALUE, published)
        assigned = assign_identifiers(proposed, published)
        self.assertEqual(assigned[-1]["identifier"], 3)
        validate(assigned, SCHEMA_VALUE, published)


class CommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Registry test")
        self.git("config", "commit.gpgsign", "false")
        self.list = self.root / LIST
        self.list.write_text(json.dumps([entry()]))
        (self.root / SCHEMA).write_text(json.dumps(SCHEMA_VALUE))
        self.git("add", ".")
        self.git("commit", "-qm", "Published list")
        self.git("branch", "published")
        self.list.write_text(json.dumps([entry(), entry("com.example.new", None)]))

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True)

    def command(self, *args):
        return subprocess.run([sys.executable, str(ROOT / ".github/scripts/registry.py"),
                               "--base-ref", "published", *args], cwd=self.root,
                              capture_output=True, text=True)

    def test_submission_then_assignment_then_strict_validation(self):
        before = self.list.read_text()
        self.assertEqual(self.command("--submission").returncode, 0)
        self.assertEqual(self.list.read_text(), before)
        self.assertNotEqual(self.command().returncode, 0)
        result = self.command("--assign")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("com.example.new: 2", result.stdout)
        self.assertEqual(self.command().returncode, 0)
        assigned = self.list.read_text()
        self.assertEqual(self.command("--assign").returncode, 0)
        self.assertEqual(self.list.read_text(), assigned)

    def test_invalid_assignment_does_not_write(self):
        proposed = json.loads(self.list.read_text())
        proposed[0]["type"] = "fingerprint"
        self.list.write_text(json.dumps(proposed))
        before = self.list.read_text()
        self.assertNotEqual(self.command("--assign").returncode, 0)
        self.assertEqual(self.list.read_text(), before)

    def test_assignment_requires_integrated_base(self):
        self.git("checkout", "-qb", "target")
        self.git("commit", "--allow-empty", "-qm", "New target commit")
        self.git("branch", "-f", "published")
        self.git("checkout", "-")
        before = self.list.read_text()
        self.assertNotEqual(self.command("--assign").returncode, 0)
        self.assertEqual(self.list.read_text(), before)


if __name__ == "__main__":
    unittest.main()
