# Organization lifecycle policy

An optional `.spindle/policy.toml` (or `SPINDLE_POLICY`) constrains candidate
authority and durable adoption without putting organization mechanics into
portable skill prose.

```toml
schema = "spindle.organization-policy/v1"

[sources]
allowed_providers = ["git", "github"]

[authority]
ceiling = "read-only"

[hooks]
required_scopes = ["repo"]

[evidence]
required_attestations = ["static-scan"]
require_certified_adapter = true

[adapters]
claude = ["2.1.220"]
codex = ["0.146.0"]
```

Inspect or audit the effective policy with:

```bash
spindle policy show --here --json
spindle policy check --here --harness codex --harness-build 0.146.0 --json
```

Policy may allow source providers, cap authority at `read-only`, `sandboxed`, or
`full`, require repo/user hook ownership, require named preflight attestations,
allow exact harness builds, and require a content-valid adapter certification.
A filename or unverified JSON object is not enough: certification identity is
recomputed before policy accepts it.

Policy checks do not install hooks or mutate skills. Candidate acquisition and
adoption call the same enforcement functions, so passing an audit is not a
bypass around the actual lifecycle boundary. Managed registry, scanner, and
attestation systems can produce inputs for these seams while Spindle retains the
exact package, authority, and runtime coordinate in its own records.
