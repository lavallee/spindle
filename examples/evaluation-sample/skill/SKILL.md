---
name: sample-diagnosis
description: Reproduce a reported failure before changing code.
---

Build a deterministic check that fails on the reported symptom before editing.
After the fix, rerun the same check and retain it as a regression test.
