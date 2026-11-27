"""Validate registry changes and assign new identifiers locally before merging."""

import argparse
import copy
import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

LIST = "softbinding-algorithm-list.json"
SCHEMA = "softbinding-algorithm-list.schema.json"


def validate(entries, schema, published=(), submission=False):
    schema = copy.deepcopy(schema)
    if submission:
        schema["items"]["required"].remove("identifier")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(entries)
    by_alg = {}
    by_id = {}
    for entry in entries:
        alg = entry["alg"]
        if alg in by_alg:
            raise ValueError(f"Duplicate alg: {alg}")
        by_alg[alg] = entry
        if "identifier" in entry:
            identifier = entry["identifier"]
            if identifier in by_id:
                raise ValueError(f"Duplicate identifier: {identifier}")
            by_id[identifier] = entry
    for old in published:
        new = by_alg.get(old["alg"])
        if new is None:
            if old["identifier"] in by_id:
                raise ValueError(f"Cannot rename published algorithm: {old['alg']}")
            # The TWG may remove malicious/non-conformant entries.
            continue
        for field in ("identifier", "alg", "type"):
            if new.get(field) != old[field]:
                raise ValueError(f"Cannot change published {field} for {old['alg']}")


def assign_identifiers(entries, published):
    """Replace new entries' provisional IDs with consecutive IDs above the base."""
    result = copy.deepcopy(entries)
    published_algs = {entry["alg"] for entry in published}
    next_id = max((entry["identifier"] for entry in published), default=-1) + 1
    for entry in result:
        if entry["alg"] not in published_algs:
            if next_id > 65535:
                raise ValueError("Identifier space exhausted (maximum 65535)")
            entry["identifier"] = next_id
            next_id += 1
    # JSON serialization follows insertion order; keep identifiers first.
    return [{"identifier": entry["identifier"], **entry} for entry in result]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--submission", action="store_true",
                      help="allow missing IDs for new entries")
    mode.add_argument("--assign", action="store_true",
                      help="assign IDs to new entries and update the list locally")
    parser.add_argument("--base-ref", default="origin/main",
                        help="freshly fetched target branch (default: origin/main)")
    args = parser.parse_args()
    published = json.loads(subprocess.check_output(
        ["git", "show", f"{args.base_ref}:{LIST}"], text=True))
    schema = json.loads(Path(SCHEMA).read_text())
    entries = json.loads(Path(LIST).read_text())
    if args.assign:
        # A current base must already be integrated before assigning final IDs.
        subprocess.run(["git", "merge-base", "--is-ancestor", args.base_ref, "HEAD"],
                       check=True)
        validate(published, schema)
        entries = assign_identifiers(entries, published)
    validate(entries, schema, published, args.submission)
    if args.assign:
        Path(LIST).write_text(json.dumps(entries, indent=4, ensure_ascii=False) + "\n")
        published_algs = {old["alg"] for old in published}
        for entry in entries:
            if entry["alg"] not in published_algs:
                print(f"{entry['alg']}: {entry['identifier']}")
    print("Submission is valid" if args.submission else "Published list is valid")


if __name__ == "__main__":
    main()
