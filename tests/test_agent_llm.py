"""Full-agent tests (require the LLM endpoint): the demo promises, asserted.

These are the two behaviours the demo video shows, and the two the judges
will probe: the ring recurrence that must be acted on, and the negative
control that must NOT be acted on.
"""

import pytest

from ledgerlens.config import CONFIG

pytestmark = pytest.mark.llm
pytestmark = pytest.mark.skipif(not CONFIG.llm_ready, reason="LLM endpoint not configured")


def test_ring_recurrence_investigation(seeded, truth_aurora):
    from ledgerlens.agents import investigate_alert
    from ledgerlens.tools import run_tool

    result = investigate_alert(seeded, "aurora", truth_aurora["live_alerts"][0])
    assert result.handoff, "analyst must hand off on ring evidence"
    assert result.case_id
    assert result.analyst_final is not None
    assert result.analyst_final.get("shape") in ("with_path", "from_memory")
    assert result.investigator_final is not None
    assert result.investigator_final.get("verdict") == "froze_and_escalated"

    hub_status = run_tool(seeded, "aurora", "get_account_profile",
                          {"account_id": truth_aurora["ring_a"]["hub"]})
    assert hub_status["data"]["status"] == "frozen", "the hub must actually be frozen"

    frozen = 0
    for m in truth_aurora["ring_a"]["mules"]:
        profile = run_tool(seeded, "aurora", "get_account_profile", {"account_id": m})
        if profile["data"]["status"] == "frozen":
            frozen += 1
    assert frozen >= 3, "most of the ring's mules must be frozen"

    case = run_tool(seeded, "aurora", "get_case", {"case_id": result.case_id})
    assert case["ok"] and case["data"]["findings"], "investigator must record findings for future sessions"
    assert case["data"]["status"] == "closed", "investigator must close the case with an outcome"


def test_negative_control_is_not_acted_on(seeded, truth_aurora):
    from ledgerlens.agents import investigate_alert
    from ledgerlens.tools import run_tool

    alert_004 = [a for a in truth_aurora["live_alerts"] if a.endswith("004")][0] \
        if any(a.endswith("004") for a in truth_aurora["live_alerts"]) else "AUR-ALR-004"
    result = investigate_alert(seeded, "aurora", alert_004)
    assert not result.handoff, "the isolated high-value alert must NOT open a case"
    assert result.case_id is None
    assert result.analyst_final is not None
    assert result.analyst_final.get("verdict") == "no_case"
    control = run_tool(seeded, "aurora", "get_account_profile",
                       {"account_id": truth_aurora["negative_control"]})
    assert control["data"]["status"] == "active", "the control account must stay unfrozen"


def test_ask_the_graph_answer_shapes(seeded):
    from ledgerlens.agents import ask_question

    res = ask_question(seeded, "aurora", "How is AUR-ACC-0950 connected to AUR-ACC-0961?")
    assert res["answer"]["shape"] == "with_path"
    assert res["answer"]["confidence"] > 0.4
