"""Validation-gated skill optimization — SkillOpt's loop, in spindle's idiom.

Transposed from microsoft/SkillOpt (verdict skillopt-validation-gated-optimization):
optimize a skill's *text* against a held-out eval set, accepting an edit ONLY if
the held-out score improves — the frozen model is never touched. Two spindle-native
invariants ride on top of SkillOpt's loop:

  - **Guardrails are a hard floor.** Every ALWAYS/NEVER/DO-NOT clause in the
    *original* skill must survive every edit — the same ``render.verify_preserved``
    check the binder enforces. An optimization may sharpen prose; it may never strip
    the floor. A guardrail-dropping edit is rejected *before* it is even scored.
  - **The gate, not taste, decides.** An edit is accepted iff the held-out score
    clears ``min_improvement``. Rejected edits go in a buffer the proposer sees, so
    it doesn't retry near-duplicates (SkillOpt's rejected-edit buffer); two
    consecutive rejects stop the run.

``score`` and ``propose`` are injected. A real run wires an eval harness + an LLM
proposer; tests inject deterministic fakes; the **advance team can call ``optimize``
to improve a surface's skills "while it sleeps"** (SkillOpt-Sleep ↔ the advance
tier) — every accepted edit is gated and guardrail-checked, so an automatic
overnight optimization can never regress a skill or strip its floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import render as render_mod

# score: skill_text -> held-out score (higher is better; any real scale works,
#   [0,1] by convention). propose: (current_best_text, rejected_labels) -> next
#   bounded edit, or None to stop.
Scorer = Callable[[str], float]
Proposer = Callable[[str, list[str]], "Optional[Edit]"]


@dataclass(frozen=True)
class Edit:
    """One bounded edit: a label, the weakness it addresses, and the transform."""

    label: str
    rationale: str
    transform: Callable[[str], str]


@dataclass
class EpochResult:
    epoch: int
    label: str
    rationale: str
    score: float          # the candidate's held-out score this epoch
    accepted: bool
    reason: str           # "improved" | "no-improvement" | "dropped-guardrail:<clause>"


@dataclass
class OptimizeResult:
    skill: str
    baseline: float
    best: float
    best_text: str
    epochs: list[EpochResult] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return sum(1 for e in self.epochs if e.accepted)

    @property
    def delta(self) -> float:
        return self.best - self.baseline

    @property
    def improved(self) -> bool:
        return self.best > self.baseline


def gate(best: float, candidate: float, min_improvement: float = 0.0) -> bool:
    """The validation gate: accept iff the candidate beats the best by the margin.

    ``min_improvement`` defaults to 0 (any strict improvement). Raise it to ignore
    score noise and demand a real gain before rewriting a skill."""
    return candidate > best + min_improvement


def optimize(
    skill_text: str,
    *,
    score: Scorer,
    propose: Proposer,
    skill: str = "skill",
    epochs: int = 5,
    min_improvement: float = 0.0,
    stop_after_rejects: int = 2,
    record: bool = True,
) -> OptimizeResult:
    """Run the validation-gated optimization loop and return the result.

    The original skill's guardrails are extracted once and enforced on every
    candidate. The loop proposes from the current *best* text, applies the edit,
    rejects it outright if it drops a guardrail, otherwise scores it on the held-out
    set and accepts via the gate. Pure except for an optional ledger record at the
    end (best-effort; never raises into the caller)."""
    original_guardrails = render_mod.extract_guardrails(skill_text)
    best_text = skill_text
    baseline = best_score = score(best_text)
    rejected: list[str] = []
    epoch_log: list[EpochResult] = []
    consecutive_rejects = 0

    for i in range(1, epochs + 1):
        edit = propose(best_text, list(rejected))
        if edit is None:
            break
        candidate = edit.transform(best_text)

        # Guardrail floor — reuse the binder's own meaning-preservation check.
        missing = render_mod.verify_preserved(skill_text, candidate) if original_guardrails else []
        if missing:
            rejected.append(edit.label)
            epoch_log.append(EpochResult(i, edit.label, edit.rationale, best_score,
                                         False, f"dropped-guardrail:{missing[0]!r}"))
            consecutive_rejects += 1
            if consecutive_rejects >= stop_after_rejects:
                break
            continue

        cand_score = score(candidate)
        if gate(best_score, cand_score, min_improvement):
            best_text, best_score = candidate, cand_score
            epoch_log.append(EpochResult(i, edit.label, edit.rationale, cand_score,
                                         True, "improved"))
            consecutive_rejects = 0
        else:
            rejected.append(edit.label)
            epoch_log.append(EpochResult(i, edit.label, edit.rationale, cand_score,
                                         False, "no-improvement"))
            consecutive_rejects += 1
            if consecutive_rejects >= stop_after_rejects:
                break

    result = OptimizeResult(skill=skill, baseline=baseline, best=best_score,
                            best_text=best_text, epochs=epoch_log)
    if record:
        _record(result)
    return result


def _record(result: OptimizeResult) -> None:
    """Append an optimization outcome to the event ledger (best-effort)."""
    try:  # pragma: no cover - ledger I/O, exercised indirectly
        from . import ledger as ledger_mod
        ledger_mod.log_event(
            "skill_optimize",
            skill=result.skill,
            baseline=result.baseline,
            best=result.best,
            delta=result.delta,
            accepted=result.accepted_count,
            epochs=len(result.epochs),
        )
    except Exception:
        pass


# ---- a real scorer seam: score by an external eval command ----------------

def command_scorer(score_cmd: str, *, timeout: int = 120) -> Scorer:  # pragma: no cover - subprocess seam
    """Build a Scorer that writes the candidate skill to a temp file and runs an
    external eval command, parsing the last float on stdout as the held-out score.

    The command receives the candidate path in ``$SPINDLE_SKILL_FILE``. This is the
    honest production seam (an eval harness, a backtest, a shadow-eval run); it is
    fail-safe — any error scores 0.0 rather than crashing the loop."""
    import os
    import re
    import subprocess
    import tempfile

    def score(text: str) -> float:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            env = {**os.environ, "SPINDLE_SKILL_FILE": path}
            proc = subprocess.run(score_cmd, shell=True, capture_output=True,
                                  text=True, timeout=timeout, env=env)
            floats = re.findall(r"-?\d+\.?\d*", proc.stdout)
            return float(floats[-1]) if floats else 0.0
        except Exception:
            return 0.0
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    return score


# ---- a real proposer seam: one bounded LLM edit per epoch ------------------

def llm_proposer(client) -> Proposer:  # pragma: no cover - LLM seam, fake-tested via injection
    """Build a Proposer backed by an LLM client (``llm.from_env``). It asks for ONE
    small, bounded improvement and returns the rewritten skill as the edit. The
    guardrail floor in ``optimize`` independently rejects any rewrite that drops an
    ALWAYS/NEVER clause, so even a careless rewrite can't strip the floor."""
    instruction = (
        "You are optimizing an agent SKILL.md. Make exactly ONE small, bounded "
        "improvement (sharpen a vague instruction, add a missing example, cut a "
        "confusing line) — not a rewrite. Preserve every ALWAYS/NEVER/DO NOT line "
        "verbatim and keep all structure. Return ONLY the full revised markdown."
    )

    def propose(current_text: str, rejected: list[str]) -> Optional[Edit]:
        avoid = ("\n\nAvoid these already-rejected edits: " + "; ".join(rejected)) if rejected else ""
        revised = client(current_text + avoid, system=instruction)
        if not revised or revised.strip() == current_text.strip():
            return None
        n = len(rejected) + 1
        return Edit(label=f"llm-edit-{n}", rationale="LLM-proposed bounded edit",
                    transform=lambda _t, r=revised: r)

    return propose
