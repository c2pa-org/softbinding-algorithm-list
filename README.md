# Soft Binding Algorithm List

C2PA specifies a mechanism for recovering a C2PA Manifest for an asset, for example when the metadata containing the C2PA Manifest has been stripped.  This mechanism is a [soft binding](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_binding), for example an invisible watermark or content fingerprint. The soft binding is used to look-up the C2PA Manifest within a Manifest Repository. The soft binding is described by the [soft binding assertion](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_bindings).

The soft binding assertion contains a field `alg` which uniquely identifies the algorithm used to compute the soft binding. The Soft Binding Algorithm List is an authoritative list of soft binding algorithm names that should be used as identifiers within the `alg` field. Entries in the list also contain additional information on the algorithms.

## Guidelines for submitting a new entry

### Pull request
Developers of soft binding algorithms may request these be added as new entries in the soft binding algorithm list. Developers may also request amendments to their entries. These requests are made by submitting a Pull Request (PR) that adds to, or edits, the [softbinding-algorithm-list JSON array](softbinding-algorithm-list.json) in this repository and following the [schema](softbinding-algorithm-list-schema.json).

### Selection rules

The C2PA Technical Working Group will approve and merge PRs in accordance with its prevailing processes for approving technical contributions to the C2PA specification. 

C2PA's Technical Working Group may also decide to remove malicious or non-conformant entries from the list of approved soft binding algorithms.

For a PR (new entry or update) to be approved the following criteria are important:
- The entry shall conform with the [schema](softbinding-algorithm-list-schema.json) and shall include all the mandatory fields.
- The entry shall not appear to be malicious (e.g., spam) or harmful.
- The PR shall be submitted by an individual affiliated with the company owning the submitted proprietary algorithm or a maintainer of the submitted open source algorithm or its fork.
- The provided URLs shall successfully resolve (e.g., `softBindingResolutionApis`, `informationalUrl`).
- The algorithm covered by the entry should support embedding or extracting a soft binding identifier for the purpose of manifest recovery. 




