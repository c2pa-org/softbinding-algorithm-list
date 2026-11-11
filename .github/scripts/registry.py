"""Validation shared by submission checks and the trusted identifier allocator."""

import copy
import json
import argparse
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
            # The TWG may remove malicious/non-conformant entries. Their IDs
            # remain reserved in the durable ledger and must not be reused.
            continue
        for field in ("identifier", "alg", "type"):
            if new.get(field) != old[field]:
                raise ValueError(f"Cannot change published {field} for {old['alg']}")


def additions(base, proposed):
    """Only additions are copied into a privileged, bot-owned integration branch."""
    before = {entry["alg"]: entry for entry in base}
    after = {entry["alg"]: entry for entry in proposed}
    for alg, entry in before.items():
        if after.get(alg) != entry:
            raise ValueError(f"Allocation PRs must only add entries; existing entry changed: {alg}")
    result = [copy.deepcopy(e) for e in proposed if e["alg"] not in before]
    if not result:
        raise ValueError("No new algorithms to register")
    return result


def reserve(ledger, published, entries, source_pr):
    """Pure allocation: durable reservations survive closed PRs and repeated runs."""
    ledger = copy.deepcopy(ledger)
    reservations = ledger.setdefault("algorithms", {})
    used = set()
    for alg, record in reservations.items():
        identifier = record["identifier"]
        if type(identifier) is not int or not 0 <= identifier <= 65535 or identifier in used:
            raise ValueError(f"Invalid allocation ledger at {alg}")
        used.add(identifier)
    for entry in published:
        alg, identifier = entry["alg"], entry["identifier"]
        if alg in reservations:
            if reservations[alg]["identifier"] != identifier:
                raise ValueError(f"Published identifier disagrees with reservation for {alg}")
        else:
            if identifier in used:
                raise ValueError(f"Published identifier collides with a reservation: {identifier}")
            reservations[alg] = {"identifier": identifier, "source_pr": None}
            used.add(identifier)
    next_id = max(ledger.get("next_identifier", 0), max(used, default=-1) + 1)
    published_algs = {entry["alg"] for entry in published}
    result = copy.deepcopy(entries)
    for entry in result:
        alg = entry["alg"]
        if alg in published_algs:
            raise ValueError(f"Algorithm already published: {alg}")
        if alg not in reservations:
            if next_id > 65535:
                raise ValueError("Identifier space exhausted (maximum 65535)")
            reservations[alg] = {"identifier": next_id, "source_pr": source_pr}
            next_id += 1
        record = reservations[alg]
        if record["source_pr"] != source_pr:
            raise ValueError(f"Algorithm is reserved by another PR: {alg}")
        # Legacy submitter-selected numbers are deliberately replaced.
        entry["identifier"] = record["identifier"]
    ledger["next_identifier"] = next_id
    return ledger, result


def validate_reservations(entries, published, ledger):
    published_algs = {entry["alg"] for entry in published}
    reservations = ledger.get("algorithms", {})
    for entry in entries:
        record = reservations.get(entry["alg"])
        if record is not None and record["identifier"] != entry["identifier"]:
            raise ValueError(f"Identifier disagrees with allocation for {entry['alg']}")
        if entry["alg"] not in published_algs and record is None:
            raise ValueError(f"No reserved identifier for {entry['alg']}; use ready-to-register")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", action="store_true")
    parser.add_argument("--published", type=Path)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    published = json.loads(args.published.read_text()) if args.published else []
    validate(json.loads(Path(LIST).read_text()), json.loads(Path(SCHEMA).read_text()),
             published, args.submission)
    if args.ledger:
        validate_reservations(json.loads(Path(LIST).read_text()), published,
                              json.loads(args.ledger.read_text()))
    print("Submission is valid" if args.submission else "Published list is valid")


if __name__ == "__main__":
    main()
