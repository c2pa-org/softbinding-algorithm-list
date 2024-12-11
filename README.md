# Soft Binding Algorithm List

C2PA specifies a mechanism for recovering a C2PA Manifest for an asset, for example when the metadata containing the C2PA Manifest has been stripped.  This mechanism is a [soft binding](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_binding) (for example an invisible watermark or content fingerprint).  The soft binding is used to look-up the C2PA Manifest within a Manifest Repository.  The soft binding is described by the [soft binding assertion](https://c2pa.org/specifications/specifications/2.0/specs/C2PA_Specification.html#_soft_bindings).

The soft binding assertion contains a field `alg` that serves to uniquely identify the algorithm used to compute the soft binding. The Soft Binding Algorithm List is an authoritative list of soft binding algorithm names that may be used as identifiers within the `alg` field. Entries in the list also contain additional information on the algorithms.

Developers of soft binding algorithms may request these be added as new entries in the soft binding algorithm list. Developers may also request amendments to their entries. These requests may be made by submitting a pull request (PR) adding to or editing the [softbinding-algorithm-list JSON array](softbinding-algorithm-list.json) in this repository and following the [entry schema](softbinding-algorithm-entry-schema.json).

The C2PA Technical Working Group may approve and merge PRs in accordance with its prevailing processes for approving technical contributions to the C2PA specification. C2PA's Technical Working Group may also decide to remove malicious or non-conformant algorithms from the list of approved soft binding algorithms.
