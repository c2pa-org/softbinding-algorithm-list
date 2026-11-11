# Soft Binding Algorithm List

C2PA specifies a mechanism for recovering a C2PA Manifest for an asset, for example when the metadata containing the C2PA Manifest has been stripped.  This mechanism is a [soft binding](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_binding), for example an invisible watermark or content fingerprint. The soft binding is used to look-up the C2PA Manifest within a Manifest Repository. The soft binding is described by the [soft binding assertion](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_bindings).

The soft binding assertion contains a field `alg` which uniquely identifies the algorithm used to compute the soft binding. The Soft Binding Algorithm List is an authoritative list of soft binding algorithm names that should be used as identifiers within the `alg` field. Entries in the list also contain additional information on the algorithms.

## Guidelines for submitting a new entry

### Pull request
Developers of soft binding algorithms may request these be added as new entries in the soft binding algorithm list. Developers may also request amendments to their entries. These requests are made by submitting a Pull Request (PR) that adds to, or edits, the [softbinding-algorithm-list JSON array](softbinding-algorithm-list.json) in this repository and following the [schema](softbinding-algorithm-list.schema.json). For new entries, omit `identifier`: the registration bot assigns it after maintainer review. All other required fields still apply. Keep existing identifiers when amending an entry.

### Selection rules

The C2PA Technical Working Group will approve and merge PRs in accordance with its prevailing processes for approving technical contributions to the C2PA specification. 

C2PA's Technical Working Group may also decide to remove malicious or non-conformant entries from the list of approved soft binding algorithms.

For a PR (new entry or update) to be approved the following criteria are important:
- The published entry shall conform with the [schema](softbinding-algorithm-list.schema.json) and shall include all mandatory fields. New-entry submissions may omit `identifier` until the registration bot assigns it.
- The entry shall not appear to be malicious (e.g., spam) or harmful.
- The PR shall be submitted by an individual affiliated with the company owning the submitted proprietary algorithm or a maintainer of the submitted open source algorithm or its fork.
- The provided URLs shall successfully resolve (e.g., `softBindingResolutionApis`, `informationalUrl`).
- `informationalUrl` shall reference documentation specific to the algorithm described by the entry. The referenced documentation shall provide a general description of the algorithm and its operation.
- The algorithm covered by the entry shall support embedding, extracting, or both, of a soft binding identifier for the purpose of manifest recovery.
- When updating an entry, the fields: `identifier`, `alg` and `type` shall not be changed.

## Automatic identifier allocation

### Contributors

Add your new entries to `softbinding-algorithm-list.json`, leaving out
`identifier`. For example:

```json
{
    "alg": "com.example.watermark.1",
    "type": "watermark",
    "decodedMediaTypes": ["image"],
    "entryMetadata": {
        "description": "An image watermark carrying an identifier for manifest recovery",
        "dateEntered": "2026-11-11T00:00:00Z",
        "contact": "developer@example.com",
        "informationalUrl": "https://example.com/watermark"
    }
}
```

Use the actual date and algorithm details. One PR may add multiple entries.
Registration PRs must only change the algorithm list and must not modify existing
entries. Submit amendments to existing entries separately, preserving their
`identifier`, `alg`, and `type`.

The `validate-json` check accepts new entries without identifiers. The separate
`publish-ready` check intentionally fails until identifiers have been reserved.
Do not merge an unallocated submission. Previously submitted provisional IDs
are accepted when valid and unique within the submission, but the bot replaces
them with its own reservations; contributors must not rely on those numbers.

### Maintainers

1. Complete the normal submission review, including affiliation, documentation,
   URL resolution and support for manifest recovery.
2. Add the **`ready-to-register`** label. Only a label applied by someone with
   repository write permission (or higher) authorizes allocation.
3. The bot permanently reserves one ID per new `alg` and opens a separate
   registration PR from a repository-owned branch. It links that PR from the
   source submission, lists the allocations and records the reviewed source SHA.
4. Review and merge the prepared registration PR after its checks pass. It
   contains only the new entries, added to the current published list. Then
   close the original submission with a link to the merged registration PR.

The bot never merges a PR or changes a contributor's fork. The public schema
continues to require integer IDs in the range 0–65535. Published identifiers,
algorithm names and types cannot change. Entries can be marked
`"deprecated": true`; the TWG may also remove malicious or non-conformant
entries under the selection rules. Removed entries' IDs remain reserved.

A prepared registration is a snapshot, not a live mirror of the source PR.
After source changes, review the new revision and remove/reapply the label.
Close any superseded registration PRs; the changed source receives a new
registration branch and the same reservations for unchanged algorithm names.
If other registrations merge first, update/rebase the prepared PR and rerun its
checks; the allocator never force-pushes or overwrites a prepared branch.

For a failed or canceled run, use **Actions → Allocate algorithm identifiers →
Run workflow**, enter the source PR number and use the default branch. The label
must still be present. Reapplying the label also retries. Repeated runs reuse
reservations and the prepared PR. If the prepared PR was closed without merging,
reopen it before retrying. The workflow log explains rejected submissions.

### Repository setup

After merging the automation:

- Create the `ready-to-register` label.
- Under **Settings → Actions → General → Workflow permissions**, enable
  **Allow GitHub Actions to create and approve pull requests**. The bot creates
  PRs but does not approve them. Organization policy must permit this setting.
  No personal access token or additional secret is required.
- Require both `validate-json` and **`publish-ready`** in the default branch's
  protection rule or ruleset, and require branches to be up to date before
  merging. This prevents a submission with missing, conflicting or unreserved
  IDs from being merged. Keep normal human review requirements.
- Protect the exact branch **`bot/identifier-allocations`** against deletion and
  force-pushes, while allowing the Actions bot to create it and make normal
  fast-forward updates. It is created on the first allocation. Exclude this
  state branch from automatic branch cleanup and keep it in repository backups.

`bot/identifier-allocations` contains `identifier-allocations.json`, the durable
allocation ledger. It is deliberately separate from the published list: closed,
failed and withdrawn registrations keep their reservations. Do not delete or
rewrite this ledger; restore it from backup if it is lost before running the
allocator again. Initial allocation imports the existing published IDs, then
assigns monotonically increasing IDs above the largest imported/reserved value.
Multiple-entry reservations are committed together. Concurrent writers use
non-force Git ref updates with retries, so they cannot reserve the same number.
A different PR cannot take another PR's reserved algorithm name.

The allocator executes only code from the trusted default branch, treats the
source PR as JSON data, rejects changes to other files, and checks the source
SHA again before preparing the registration. Its workflow has narrowly scoped
write permissions. Validation workflows have read-only permissions. The bot
explicitly dispatches validation on the prepared branch, so checks also run when
bot-created PR events do not start workflows automatically. This uses
[GitHub's documented workflow-dispatch exception](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow).

### Local checks

Use Python 3.12 or later:

```sh
python -m pip install jsonschema==4.26.0
python -m unittest discover -s .github/scripts -p 'test_*.py' -v
python .github/scripts/registry.py
```

For a new-entry submission, pass `--submission`. CI additionally compares the
submission with the target branch to protect published identity fields; the
strict `publish-ready` check verifies new IDs against the allocation ledger.
