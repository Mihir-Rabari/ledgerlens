"""The evolution features: policy citations, session timeline, memory-evolving
playbooks, and the enriched component feed."""

from ledgerlens.tools import run_tool


def test_policy_search_returns_citable_sections(seeded):
    res = run_tool(seeded, "aurora", "search_policies", {"text": "freeze"})
    assert res["ok"]
    sections = res["data"]["sections"]
    assert sections, "policy search must find the freeze authority matrix"
    assert any(s["policy"] == "POL-31" for s in sections)
    assert all("effective" in s for s in sections), "every policy section carries its source date"


def test_policy_chunk_fetch_exact(seeded):
    res = run_tool(seeded, "aurora", "get_policy_chunks", {"chunk_ids": ["POL-22-C01"]})
    assert res["ok"]
    chunk = res["data"]["chunks"][0]
    assert chunk["policy"] == "POL-22" and chunk["idx"] == "1"
    assert "10,000" in chunk["text"] or "10000" in chunk["text"]


def test_sessions_timeline_shows_seeded_handoff(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "list_sessions", {})
    assert res["ok"]
    sessions = res["data"]["sessions"]
    assert len(sessions) >= 2
    handed = [s for s in sessions if s["handed_from"]]
    assert handed, "the seeded past-case handoff must appear in the timeline"
    investigators = [s for s in sessions if s["agent"] == "case-investigator" and s["findings"] > 0]
    assert investigators, "the past investigator session must show its produced findings"


def test_component_graph_includes_internal_money(seeded, truth_aurora):
    members = [truth_aurora["ring_a"]["hub"]] + truth_aurora["ring_a"]["mules"]
    res = run_tool(seeded, "aurora", "component_graph", {"member_ids": members})
    assert res["ok"]
    assert len(res["data"]["transfers"]) >= 6, "the six mule legs must appear as money edges"
    total = sum(t["amount"] for t in res["data"]["transfers"])
    assert total > 40_000


def test_learn_lesson_appends_sourced_step(seeded, truth_verdant):
    case_res = run_tool(seeded, "verdant", "open_case", {"title": "Lesson probe", "severity": 1,
                                                         "agent": "pytest"})
    case_id = case_res["data"]["case_id"]
    before = run_tool(seeded, "verdant", "get_playbook", {"playbook": "structuring"})["data"]["steps"]
    res = run_tool(seeded, "verdant", "learn_lesson",
                   {"case_id": case_id, "playbook": "structuring",
                    "text": "Probe step: verify aggregation window before escalating."})
    assert res["ok"], res
    after = run_tool(seeded, "verdant", "get_playbook", {"playbook": "structuring"})["data"]["steps"]
    assert len(after) == len(before) + 1
    learned = [s for s in after if s.get("source") == case_id]
    assert learned and learned[0]["action"] == "learned"
    assert learned[0].get("learned_at"), "a learned step must carry the date it was learned"


def test_learn_lesson_unknown_case(seeded):
    res = run_tool(seeded, "aurora", "learn_lesson",
                   {"case_id": "CASE-NOPE", "playbook": "structuring", "text": "x"})
    assert not res["ok"] and res["error"]["shape"] == "unknown_entity"
