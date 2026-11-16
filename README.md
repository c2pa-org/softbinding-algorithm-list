# Soft Binding Algorithm List

C2PA specifies a mechanism for recovering a C2PA Manifest for an asset, for example when the metadata containing the C2PA Manifest has been stripped.  This mechanism is a [soft binding](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_binding), for example an invisible watermark or content fingerprint. The soft binding is used to look-up the C2PA Manifest within a Manifest Repository. The soft binding is described by the [soft binding assertion](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_bindings).

The soft binding assertion contains a field `alg` which uniquely identifies the algorithm used to compute the soft binding. The Soft Binding Algorithm List is an authoritative list of soft binding algorithm names that should be used as identifiers within the `alg` field. Entries in the list also contain additional information on the algorithms.

## Guidelines for submitting a new entry

### Pull request
Developers of soft binding algorithms may request these be added as new entries in the soft binding algorithm list. Developers may also request amendments to their entries. These requests are made by submitting a Pull Request (PR) that adds to, or edits, the [softbinding-algorithm-list JSON array](softbinding-algorithm-list.json) in this repository and following the [schema](softbinding-algorithm-list.schema.json). For new entries, omit `identifier`: a maintainer assigns it locally before merge. All other required fields still apply. Keep existing identifiers when amending an entry.

### Selection rules

The C2PA Technical Working Group will approve and merge PRs in accordance with its prevailing processes for approving technical contributions to the C2PA specification. 

C2PA's Technical Working Group may also decide to remove malicious or non-conformant entries from the list of approved soft binding algorithms.

For a PR (new entry or update) to be approved the following criteria are important:
- The published entry shall conform with the [schema](softbinding-algorithm-list.schema.json) and shall include all mandatory fields. New-entry submissions may omit `identifier` until a maintainer assigns it.
- The entry shall not appear to be malicious (e.g., spam) or harmful.
- The PR shall be submitted by an individual affiliated with the company owning the submitted proprietary algorithm or a maintainer of the submitted open source algorithm or its fork.
- The provided URLs shall successfully resolve (e.g., `softBindingResolutionApis`, `informationalUrl`).
- `informationalUrl` shall reference documentation specific to the algorithm described by the entry. The referenced documentation shall provide a general description of the algorithm and its operation.
- The algorithm covered by the entry shall support embedding, extracting, or both, of a soft binding identifier for the purpose of manifest recovery.
- When updating an entry, the fields: `identifier`, `alg` and `type` shall not be changed.

## Assigning identifiers before merge

Contributors add new entries without `identifier`; maintainers assign IDs locally
in the same PR after technical review. The public schema still requires IDs for
published entries. `validate-json` accepts ID-less new entries, while
`publish-ready` intentionally fails until IDs are assigned. Both checks reject
duplicate algorithm names or IDs and changes to published `identifier`, `alg`,
or `type` fields. Normal amendments and TWG removals remain possible.

Maintainers process new registrations one at a time:

1. Check out the contribution's PR branch in a local clone. Fetch the target
   repository's current `main` and merge or rebase it into the PR branch.
2. Install the validator and assign IDs (replace `origin/main` if your target
   repository uses another remote):

   ```sh
   python3 -m pip install jsonschema==4.26.0
   python3 .github/scripts/registry.py --assign --base-ref origin/main
   ```

3. Review the diff, commit the updated JSON, and push to the same PR branch.
   If you cannot push to the contributor's branch, provide the assignment patch
   for the contributor to commit.
4. Merge after normal review and both checks pass. If another registration
   merges first, update the branch and rerun the command before merging.

The command assigns consecutive IDs above the target list's highest ID to all
new entries, replacing any provisional IDs. Existing entries keep their IDs.
It requires the selected base to be an ancestor of the checked-out branch and
validates the complete result before writing. Always fetch before running it:
the command reads local Git refs and does not contact GitHub. IDs are provisional
until merged; there is no separate reservation ledger or bot-created PR.

Require **`validate-json`** and **`publish-ready`** in the target branch's
protection rule or ruleset, together with **Require branches to be up to date
before merging**. Keep normal human review requirements. No label, bot secret,
write-enabled workflow, or state branch is needed.

For local read-only checks and tests:

```sh
python3 .github/scripts/registry.py --submission --base-ref origin/main
python3 .github/scripts/registry.py --base-ref origin/main
python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v
```

The first command allows new entries without IDs; the second requires a complete
published list. The test suite covers validation, assignment, and the local CLI.
