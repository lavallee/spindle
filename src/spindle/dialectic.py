"""Dialectic routing — turn two opposed readings of an upstream change into one
action, escalating to a human only on genuine divergence.

This is the decision core of the ingest dialectic (see
``plans/spindle-evolution/concept.md`` §2 and ``ingest-synthesis.md``). Two agents
read a notable upstream change with asymmetric priors:

  - **concordant** — *our doctrine is the reference.* Does this fit/extend what we
    already believe? (``concordant_fits``)
  - **discordant** — *the upstream is the reference; our doctrine is on trial.* Is
    this a challenge to our frame? (``discordant_challenges``)

Their (dis)agreement is the escalation signal, crossed with an orthogonal
**relevance** axis (do our repos actually need this?):

    coherence \\ relevance     relevant            not relevant
    -----------------------    -----------------   ----------------------
    concordant (both agree)    ACCRUE              FOLD_QUIETLY
    discordant (divergence)    ESCALATE (gate)     NOTE
    neither ("nothing here")   DROP                DROP

Only ESCALATE involves a human — filed as a decision gate (tag
``spindle:doctrine``) carrying the adjudicator's {crux, doctrine diff, pilot}. Everything else is
automatic. This is the mechanism behind "no proposal queue; human only at genuine
tradeoffs."
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Actions
DROP = "drop"                  # neither agent found anything — discard
ACCRUE = "accrue"              # both agree it fits + relevant — auto-absorb
FOLD_QUIETLY = "fold_quietly"  # fits but not repo-relevant — note in doctrine, no per-repo action
ESCALATE = "escalate"          # divergence + relevant — file a decision gate
NOTE = "note"                  # divergence but not relevant — record, don't spend a human


@dataclass(frozen=True)
class Routing:
    action: str
    files_gate: bool   # does this route file a spindle:doctrine gate?
    reason: str


def coherence_outcome(concordant_fits: bool, discordant_challenges: bool) -> str:
    """Collapse the two readings into the coherence axis.

    A frame-*challenge* dominates: if the discordant agent makes a real challenge,
    the pair is *discordant* (divergence) even if the concordant agent also saw a
    fit — that combination ("fits fine" vs. "no, this challenges us") is exactly
    the divergence worth a human. If there's no challenge, then either it fits
    (concordant) or there was nothing to absorb (nothing).
    """
    if discordant_challenges:
        return "discordant"
    if concordant_fits:
        return "concordant"
    return "nothing"


def route(concordant_fits: bool, discordant_challenges: bool, relevant: bool) -> Routing:
    """Map the dialectic + relevance to a single action. See module docstring."""
    outcome = coherence_outcome(concordant_fits, discordant_challenges)
    if outcome == "nothing":
        return Routing(DROP, False, "neither reading found anything to absorb")
    if outcome == "concordant":
        if relevant:
            return Routing(ACCRUE, False, "both agree it fits and our repos need it — auto-absorb")
        return Routing(FOLD_QUIETLY, False, "fits doctrine but no repo needs it — fold quietly, no per-repo action")
    # discordant
    if relevant:
        return Routing(ESCALATE, True, "readings diverge on a relevant change — frame-challenge; file a gate for a human")
    return Routing(NOTE, False, "readings diverge but no repo needs it — record, don't spend a human")


# ---- parsing the readings' machine-readable footers ---------------------

_YAML_BLOCK_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)
_TRUE = {"true", "yes", "1"}


def _bool_field(text: str, key: str) -> bool:
    """Read a ``key: true|false`` line from a yaml block (or loose lines)."""
    m = _YAML_BLOCK_RE.search(text)
    body = m.group(1) if m else text
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(key + ":"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'").lower() in _TRUE
    return False


def route_reports(concordant_report: str, discordant_report: str, *, relevant: bool) -> Routing:
    """Route from the two passes' reports: read ``concordant_fits`` /
    ``discordant_challenges`` from their footers and apply :func:`route`.

    The runner that executes the sub-passes is outside the core; this is the
    decided Spindle-side step that turns their outputs into one action.
    """
    return route(
        concordant_fits=_bool_field(concordant_report, "concordant_fits"),
        discordant_challenges=_bool_field(discordant_report, "discordant_challenges"),
        relevant=relevant,
    )
