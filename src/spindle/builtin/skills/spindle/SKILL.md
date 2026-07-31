---
name: spindle
description: Operate Spindle's evidence-bearing lifecycle for agent skills. Use to inspect, discover, try, borrow, adopt, update, distill, disable, roll back, or retire a skill; explain active skill state; or diagnose startup, conflict, version, and harness state. Do not trigger for ordinary work that merely uses an active skill.
---

# Spindle

Drive the installed CLI; do not reproduce its lifecycle logic.

1. Run `spindle harness context --here --json` in the relevant repository. If
   detection is ambiguous, add `--harness codex` or `--harness claude`.
2. Use its state, blockers, receipts, and action contracts as current facts.
   Availability is not activation; activation is not evidence of improvement.
3. Choose the smallest action matching the request. Prefer inspection or a
   temporary trial unless durable adoption was requested.
4. Before mutation, run the returned dry-run command. Proceed only when the
   request authorizes that exact change or the user approves the plan.
5. Refresh context after mutation and report resulting state and receipt IDs.

Never alter foreign harness state or infer durable adoption. If the CLI or a
required command is unavailable, report the exact gap; do not invent flags.
