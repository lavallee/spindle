"""Tests for spindle.dialectic — the concept §2 routing 2x2 + disagreement rule."""

from __future__ import annotations

import spindle.dialectic as d


def test_coherence_outcome_three_ways():
    assert d.coherence_outcome(concordant_fits=True, discordant_challenges=False) == "concordant"
    assert d.coherence_outcome(concordant_fits=False, discordant_challenges=False) == "nothing"
    assert d.coherence_outcome(concordant_fits=True, discordant_challenges=True) == "discordant"
    # A challenge dominates even if concordant saw no fit
    assert d.coherence_outcome(concordant_fits=False, discordant_challenges=True) == "discordant"


def test_route_nothing_drops_regardless_of_relevance():
    for relevant in (True, False):
        r = d.route(concordant_fits=False, discordant_challenges=False, relevant=relevant)
        assert r.action == d.DROP
        assert r.files_gate is False


def test_route_concordant_relevant_accrues():
    r = d.route(concordant_fits=True, discordant_challenges=False, relevant=True)
    assert r.action == d.ACCRUE
    assert r.files_gate is False


def test_route_concordant_irrelevant_folds_quietly():
    r = d.route(concordant_fits=True, discordant_challenges=False, relevant=False)
    assert r.action == d.FOLD_QUIETLY
    assert r.files_gate is False


def test_route_divergence_relevant_escalates_and_files_gate():
    r = d.route(concordant_fits=True, discordant_challenges=True, relevant=True)
    assert r.action == d.ESCALATE
    assert r.files_gate is True


def test_route_divergence_irrelevant_notes_no_gate():
    r = d.route(concordant_fits=True, discordant_challenges=True, relevant=False)
    assert r.action == d.NOTE
    assert r.files_gate is False


def test_only_escalate_files_a_gate():
    """The whole 2x2: exactly one cell files a human gate."""
    gate_cells = []
    for cf in (True, False):
        for dc in (True, False):
            for rel in (True, False):
                r = d.route(cf, dc, rel)
                if r.files_gate:
                    gate_cells.append((cf, dc, rel))
    # Only divergence (discordant_challenges) + relevant escalates.
    assert gate_cells == [(True, True, True), (False, True, True)]


def test_every_route_has_a_reason():
    for cf in (True, False):
        for dc in (True, False):
            for rel in (True, False):
                assert d.route(cf, dc, rel).reason


# ---- routing from reports -----------------------------------------------

CONCORDANT_FITS = '''
report prose...
```yaml
concordant_fits: true
touches: [P1]
whats_new: "a refinement"
```
'''
DISCORDANT_CHALLENGE = '''
report prose...
```yaml
discordant_challenges: true
within_or_to: "to"
give_up: "P5"
```
'''
DISCORDANT_NONE = '```yaml\ndiscordant_challenges: false\n```\n'


def test_route_reports_divergence_relevant_escalates():
    r = d.route_reports(CONCORDANT_FITS, DISCORDANT_CHALLENGE, relevant=True)
    assert r.action == d.ESCALATE
    assert r.files_gate is True


def test_route_reports_agreement_accrues():
    r = d.route_reports(CONCORDANT_FITS, DISCORDANT_NONE, relevant=True)
    assert r.action == d.ACCRUE


def test_route_reports_loose_lines_no_yaml_fence():
    r = d.route_reports("concordant_fits: false", "discordant_challenges: false", relevant=True)
    assert r.action == d.DROP


def test_bool_field_missing_defaults_false():
    assert d._bool_field("no footer here", "concordant_fits") is False
