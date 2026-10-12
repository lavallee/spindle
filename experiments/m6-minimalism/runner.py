"""Deterministic contract fixture; it does not claim model behavior."""

import json
import os
from pathlib import Path


fixture = json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text())
arm = os.environ["SPINDLE_EVAL_ARM"]
status = "not-applicable" if arm == "no-skill" else "pass"
gates = {
    gate: {
        "status": "pass" if gate == "behavior" else status,
        "evidence": (
            f"deterministic fixture {os.environ['SPINDLE_EVAL_CASE_ID']}"
            if gate == "behavior" or status == "pass"
            else None
        ),
    }
    for gate in (
        "availability",
        "activation",
        "routing",
        "authorization",
        "behavior",
        "adapter",
    )
}
result = {
    "score": fixture["scores"][arm],
    "gates": gates,
    "evidence": {
        "source": "checked-in deterministic M6 contract fixture",
        "repeat": os.environ["SPINDLE_EVAL_REPEAT"],
    },
    "metrics": {"human_corrections": 0},
}
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(
    json.dumps(result), encoding="utf-8"
)
