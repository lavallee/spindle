# M6 named-arm minimalism evidence

This checked-in experiment proves the named-arm, repeated-pair,
non-inferiority, hard-floor, efficiency, separated-gate, and coordinate-drift
contracts with a deterministic runner. It is executable contract evidence, not a
claim about model quality.

```bash
uv run spindle eval matrix validate experiments/m6-minimalism/manifest.toml
uv run spindle eval matrix run \
  experiments/m6-minimalism/manifest.toml --split held_out
```

The retained receipt is
`receipts/m6-empty-overlay-32918ba56b64.json`, identity
`sha256:32918ba56b641bf9e197da9caf31ed32e8fb8bad9ce9b738cee9d84e20af836e`.
It records all 30 runs: five named arms, two held-out cases, and three repeats.
The zero-byte `empty-overlay` arm is 203 bytes smaller than the incumbent, has a
mean paired delta and one-sided 95% lower bound of approximately `-0.01` against
the predeclared `-0.03` margin, holds the `0.70` floor with a minimum `0.79`, and
passes availability, activation, routing, authorization, behavior, and adapter
gates separately.

The task distribution digest is
`sha256:01e178bad198c7043199ea2da0c9f766dd90436138f0c04390a62b289616d75d`;
the complete runtime coordinate digest is
`sha256:f166a426f6cd92b7451118fe588c1250ed86fc6f3d1f38e4459a01d35540c839`.
Supplying `model=fixture-frontier-v2` with the other five coordinates unchanged
returns `rebaseline-required` and names only `model` as changed.

The unit and CLI suite separately retain a hard-floor failure, verify receipt
tamper detection, classify package resources, route a deterministic script to
`chip-or-tool`, keep reference knowledge progressively disclosed, and stage one
section deletion into a new local trial revision without modifying the source or
creating adoption state.
