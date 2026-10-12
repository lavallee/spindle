# Milestone 4 pinned-remote evidence

Status: complete, 2026-07-31.

This directory records the public-source and live-trial boundary for pinned
remote candidates. Large Git object caches, exported snapshots, package cache,
and harness output stay outside the repository; only content-addressed IDs and
the non-sensitive task fixture are retained here.

## Coordinate

- Source: `skills.sh:vercel-labs/agent-skills@7c180d9044c9ae2b442b567aad4e42a28dd5ed62#web-design-guidelines`
- Resolved Git tree: `0557b732b3907e51bed3fd7898095f8097a0834e`
- Package: `agent-skills@7c180d9044c9`, digest
  `sha256:b8d51467afcbac534af588e32296047bc2a93cbc5d8bdd6a3576a106f63ba004`
- Skill digest:
  `sha256:6a15c2b70727848c9e03e14a2347205e648e7735765be53fd459f42d41e89948`
- Harness: Codex CLI 0.146.0, requested model `gpt-5.6-sol`, ephemeral
  read-only/no-approval launch posture
- Task digest:
  `sha256:3cc8193ad79c6ebe3a8fbf1f26d9a90b8370baebe853db30246e4071fe910b7c`

## Evidence chain

- Source receipt:
  `sha256:49c57525007e0050daaad03bfd240fea7a3179d1a7635f64111ae7173eba8832`
- Static preflight:
  `sha256:355d51f071248daabe1171479619ad41d086f7dce9ecbc7e6f4e426047376e18`;
  structure and provenance passed, one selected-skill network indicator was
  explicitly approved, and no bundled code executed.
- Lease plan:
  `sha256:99efd56f0450b6bc8e95ebb280de5fdc5068b421504492c9875dc0767663f358`
- Session lease:
  `sha256:2fd76269baf57f14b3a434aae7ecd94c6c762d5d0ce2691aadea5e822c396278`
- Startup receipt:
  `sha256:3e14980359eac3f6c08f87a2c6f9f1e0e863a3536cf266e64a65205283f31e13`
- Activation receipt:
  `ebcf3bc97d0e8d972f39cb0606f81e30b77d280ee9d71ac6fc1ae9337d6f5548`
- Trial run:
  `sha256:fec337aa0f168c0667be836aaeff258b0ff201f8bcdde5dd84a0eb15e02e1ae4`;
  exit code 0, with stdout/stderr retained only as digests.
- Cleanup event:
  `sha256:b040e525ffb155ee290dba6b8f8b013f065dd66747c6b36966d921ef1d65142f`;
  it removed the exact owned repo projection and returned the lock to zero
  leases and zero adoptions.

The deterministic archive `public-codex-evidence.tar.gz` has SHA-256
`d02f9467d148d74902131c26008fc81f8441fef83712d26bd64ebd4c8a94a095`.
It contains only the receipts above, the cleanup plan/startup receipt, and the
final empty surface lock. It excludes fetched source/package bytes, Git objects,
harness output, credentials, and non-addressed observation logs.

An initial diagnostic run used an isolated `HOME`; the local Codex launcher then
fell back to an incomplete npm cache and exited before model work. The lease was
still released exactly. That generated 253 MiB temporary npm home was deleted
after the failure was identified; it contained no source-of-record evidence.
The successful run kept Spindle state isolated while using the existing Codex
configuration home. Existing foreign user skills were inventoried as warnings
and remained unchanged.
