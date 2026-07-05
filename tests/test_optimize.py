"""Tests for spindle.optimize — the validation-gated optimization loop. All offline:
the scorer and proposer are deterministic fakes, so the gate, the guardrail floor,
and the rejected-edit buffer are exercised without an LLM or eval harness."""

from __future__ import annotations

import spindle.optimize as optimize
from spindle.optimize import Edit

SKILL = """\
# demo skill

Do the thing well.

ALWAYS validate input.
NEVER delete without confirmation.
"""


def _edit(label, fn):
    return Edit(label=label, rationale=label, transform=fn)


def _proposer(edits):
    """A proposer that yields a fixed list of edits, then None."""
    seq = iter(edits)

    def propose(current, rejected):
        return next(seq, None)
    return propose


# ---- the gate -----------------------------------------------------------

def test_gate_accepts_only_strict_improvement():
    assert optimize.gate(0.5, 0.6) is True
    assert optimize.gate(0.5, 0.5) is False
    assert optimize.gate(0.5, 0.4) is False


def test_gate_honors_min_improvement():
    assert optimize.gate(0.5, 0.55, min_improvement=0.1) is False
    assert optimize.gate(0.5, 0.65, min_improvement=0.1) is True


# ---- accept / reject by held-out score ----------------------------------

def test_optimize_accepts_improving_edit():
    # scorer rewards the token GOOD in the text
    score = lambda t: 1.0 if "GOOD" in t else 0.0
    edits = [_edit("add-good", lambda t: t + "\nGOOD\n")]
    r = optimize.optimize(SKILL, score=score, propose=_proposer(edits), record=False)
    assert r.improved and r.delta == 1.0
    assert r.accepted_count == 1
    assert "GOOD" in r.best_text


def test_optimize_rejects_non_improving_edit():
    score = lambda t: 0.5  # flat — nothing ever improves
    edits = [_edit("noop", lambda t: t + "\nfiller\n")]
    r = optimize.optimize(SKILL, score=score, propose=_proposer(edits), record=False)
    assert not r.improved
    assert r.best_text == SKILL                 # unchanged
    assert r.epochs[0].reason == "no-improvement"


# ---- the guardrail floor (reuses render.verify_preserved) ----------------

def test_guardrail_dropping_edit_rejected_unscored():
    calls = {"n": 0}
    def score(t):
        calls["n"] += 1
        return 1.0  # would "improve" if it were ever scored
    # an edit that strips a NEVER guardrail
    bad = _edit("strip-guardrail",
                lambda t: t.replace("NEVER delete without confirmation.", ""))
    r = optimize.optimize(SKILL, score=score, propose=_proposer([bad]), record=False)
    assert not r.improved
    assert "NEVER delete without confirmation." in r.best_text
    assert r.epochs[0].reason.startswith("dropped-guardrail")
    # baseline scored once; the guardrail-dropping candidate was NEVER scored
    assert calls["n"] == 1


# ---- rejected buffer + stopping -----------------------------------------

def test_rejected_labels_passed_to_proposer():
    seen = []
    def propose(current, rejected):
        seen.append(list(rejected))
        if len(seen) > 2:
            return None
        return _edit(f"e{len(seen)}", lambda t: t + "x")  # never improves (flat score)
    optimize.optimize(SKILL, score=lambda t: 0.5, propose=propose,
                      stop_after_rejects=99, record=False)
    # second proposal sees the first rejected label
    assert seen[0] == [] and seen[1] == ["e1"]


def test_two_consecutive_rejects_stops():
    edits = [_edit(f"e{i}", lambda t: t + "x") for i in range(5)]
    r = optimize.optimize(SKILL, score=lambda t: 0.5, propose=_proposer(edits),
                          stop_after_rejects=2, epochs=5, record=False)
    assert len(r.epochs) == 2                    # stopped after 2 rejects, not 5


def test_proposer_none_stops_loop():
    r = optimize.optimize(SKILL, score=lambda t: 0.5,
                          propose=lambda c, rej: None, record=False)
    assert r.epochs == []
    assert r.best == r.baseline


# ---- a multi-epoch run that climbs --------------------------------------

def test_optimize_climbs_over_epochs():
    # each "good" token adds 0.25; proposer adds one per epoch
    score = lambda t: 0.25 * t.count("GOOD")
    edits = [_edit(f"g{i}", lambda t: t + "\nGOOD\n") for i in range(3)]
    r = optimize.optimize(SKILL, score=score, propose=_proposer(edits),
                          epochs=3, record=False)
    assert r.accepted_count == 3
    assert r.best == 0.75 and r.baseline == 0.0
    assert all(e.accepted for e in r.epochs)
