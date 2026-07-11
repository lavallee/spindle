"""Deterministic example runner for the public evaluation contract."""

from __future__ import annotations

import json
import os
from pathlib import Path


fixture = json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text(encoding="utf-8"))
arm = os.environ["SPINDLE_EVAL_ARM"]
result = {
    "score": fixture[arm]["score"],
    "passed": fixture[arm]["score"] >= 0.5,
    "skill_invoked": arm == "variant",
    "evidence": {
        "grader": "deterministic-example",
        "observed": fixture[arm]["observed"],
    },
    "metrics": fixture[arm].get("metrics", {}),
    "artifacts": [],
}
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(
    json.dumps(result), encoding="utf-8"
)
