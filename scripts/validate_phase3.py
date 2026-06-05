from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from validate_human_approval_gate import validate_human_approval_gate  # noqa: E402
from validate_repair_agent import validate_repair_agent_handler, validate_resume_repair_log  # noqa: E402
from validate_retry_policy import (  # noqa: E402
    validate_policy_decisions,
    validate_resume_auto_retry,
    validate_retry_budget_exhaustion,
)
from validate_stale_detector import (  # noqa: E402
    validate_health_states,
    validate_resume_conversion,
    validate_supervision_outputs,
)


def main() -> int:
    now = datetime(2026, 5, 20, 13, 0, tzinfo=timezone.utc)

    drills = [
        ("stale health classification", lambda: validate_health_states(now)),
        ("stale supervision exposure", lambda: validate_supervision_outputs(now)),
        ("stale resume conversion", lambda: validate_resume_conversion(now)),
        ("retry policy decisions", lambda: validate_policy_decisions(now)),
        ("retry auto replay", lambda: validate_resume_auto_retry(now)),
        ("retry budget blocked repair", lambda: validate_retry_budget_exhaustion(now)),
        ("repair-agent handler", lambda: validate_repair_agent_handler(now)),
        ("repair log exposure", lambda: validate_resume_repair_log(now)),
        ("human approval gate", lambda: validate_human_approval_gate(now)),
    ]

    for name, drill in drills:
        drill()
        print(f"Phase 3 drill passed: {name}")

    print("Phase 3 validation passed.")
    print("Checked supervision, stale detection, retry policy, repair-agent, repair log, approval gate, and resume replay.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
