"""Answer shapes: the typed-error protocol must survive every failure mode."""

from ledgerlens.tools import run_tool


def test_unknown_entity_shape(seeded):
    res = run_tool(seeded, "aurora", "get_account_profile", {"account_id": "AUR-ACC-9999"})
    assert not res["ok"] and res["error"]["shape"] == "unknown_entity"


def test_not_in_graph_shape_for_unconnected_pair(seeded, truth_aurora):
    control = truth_aurora["negative_control"]
    # control is isolated; trace to a ring mule must find no transfer path
    res = run_tool(seeded, "aurora", "trace_money_path",
                   {"from_account_id": control, "to_account_id": truth_aurora["ring_a"]["mules"][3]})
    assert not res["ok"] and res["error"]["shape"] == "not_in_graph"
    assert "graph does not know" in res["error"]["detail"]


def test_playbook_name_normalization(seeded):
    res = run_tool(seeded, "aurora", "get_playbook", {"playbook": "rapid_velocity"})
    assert res["ok"] and len(res["data"]["steps"]) == 6
    res = run_tool(seeded, "aurora", "get_playbook", {"playbook": "rapid-velocity"})
    assert res["ok"] and len(res["data"]["steps"]) == 6


def test_missing_playbook_is_not_in_graph(seeded):
    res = run_tool(seeded, "aurora", "get_playbook", {"playbook": "no-such-sop"})
    assert not res["ok"] and res["error"]["shape"] == "not_in_graph"


def test_unknown_tool_is_structured(seeded):
    res = run_tool(seeded, "aurora", "make_coffee", {})
    assert not res["ok"] and res["error"]["shape"] == "unknown_tool"


def test_component_graph_feed_for_visualizer(seeded, truth_aurora):
    members = [truth_aurora["ring_a"]["hub"]] + truth_aurora["ring_a"]["mules"]
    res = run_tool(seeded, "aurora", "component_graph", {"member_ids": members})
    assert res["ok"]
    assert len(res["data"]["nodes"]) == 7
    assert res["data"]["edges"], "the visualizer needs association edges"
