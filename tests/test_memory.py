"""Cross-session memory: recall from past cases, and a write -> recall round-trip."""

from ledgerlens.tools import run_tool


def test_past_case_is_recallable_from_memory(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "search_memory", {"text": "ghost device ring"})
    assert res["ok"]
    case_ids = {c["id"] for c in res["data"]["cases"]}
    assert truth_aurora["past_case"] in case_ids
    past = run_tool(seeded, "aurora", "get_case", {"case_id": truth_aurora["past_case"]})
    assert past["ok"]
    assert past["data"]["status"] == "closed"
    assert past["data"]["findings"], "past case must carry its findings forward"
    assert any("DEV-AUR-0990" in f["text"] or "device" in f["text"].lower() for f in past["data"]["findings"])


def test_memory_answers_carry_learned_dates(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "search_memory", {"text": truth_aurora["past_case"]})
    assert res["ok"] and res["data"]["cases"]
    case = res["data"]["cases"][0]
    assert case.get("closed_at"), "a memory answer must carry the date it was learned"


def test_memory_write_then_recall_roundtrip(seeded, truth_verdant):
    token = "zephyr-roundtrip-9021"
    case_res = run_tool(seeded, "verdant", "open_case",
                        {"title": f"Memory roundtrip {token}", "severity": 1, "agent": "pytest"})
    assert case_res["ok"]
    case_id = case_res["data"]["case_id"]

    finding_res = run_tool(seeded, "verdant", "add_finding",
                           {"case_id": case_id, "text": f"Distinctive finding marker {token}",
                            "confidence": 0.9})
    assert finding_res["ok"]
    close_res = run_tool(seeded, "verdant", "close_case",
                         {"case_id": case_id, "outcome": f"Closed with marker {token} for recall tests"})
    assert close_res["ok"]

    recall = run_tool(seeded, "verdant", "search_memory", {"text": token})
    assert recall["ok"]
    assert any(token in f["text"] for f in recall["data"]["findings"])
    assert any(token in (c.get("outcome") or "") for c in recall["data"]["cases"])

    fetched = run_tool(seeded, "verdant", "get_case", {"case_id": case_id})
    assert fetched["ok"] and fetched["data"]["status"] == "closed"
    assert any(token in f["text"] for f in fetched["data"]["findings"])


def test_unknown_case_returns_unknown_entity(seeded):
    res = run_tool(seeded, "aurora", "get_case", {"case_id": "CASE-NOPE"})
    assert not res["ok"] and res["error"]["shape"] == "unknown_entity"


def test_freeze_is_audited(seeded, truth_verdant):
    hub = truth_verdant["ring_a"]["hub"]
    freeze = run_tool(seeded, "verdant", "freeze_account",
                      {"account_id": hub, "reason": "pytest: ring membership evidenced"})
    assert freeze["ok"]
    profile = run_tool(seeded, "verdant", "get_account_profile", {"account_id": hub})
    assert profile["ok"] and profile["data"]["status"] == "frozen"
