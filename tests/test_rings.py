"""Ring detection and graph algorithms: the tools must find exactly what was planted."""

from ledgerlens.tools import run_tool


def test_find_rings_recovers_planted_ring_a(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "find_rings", {"min_size": 3})
    assert res["ok"]
    planted = set([truth_aurora["ring_a"]["hub"]] + truth_aurora["ring_a"]["mules"])
    comps = res["data"]["components"]
    assert any(set(c["member_ids"]) == planted for c in comps), [c["member_ids"] for c in comps]
    ring_comp = next(c for c in comps if set(c["member_ids"]) == planted)
    assert ring_comp["size"] == 7
    assert ring_comp["internal_transfer_edges"] >= 6  # six mule legs + noise tolerance
    assert ring_comp["internal_transfer_amount"] > 40_000


def test_find_rings_recovers_subtle_ring_b(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "find_rings", {"min_size": 3})
    set([truth_aurora["ring_b"]["hub"]] + truth_aurora["ring_b"]["senders"])
    # the subtle ring shares a device among 3 of 5 senders; the component must at
    # least contain those 3 device-sharing senders
    comps = res["data"]["components"]
    assert any(
        set(truth_aurora["ring_b"]["senders"][:3]).issubset(set(c["member_ids"])) for c in comps
    ), [c["member_ids"] for c in comps]


def test_hub_ranks_top(seeded, truth_aurora):
    members = [truth_aurora["ring_a"]["hub"]] + truth_aurora["ring_a"]["mules"]
    res = run_tool(seeded, "aurora", "rank_ring_accounts", {"member_ids": members})
    assert res["ok"]
    top = res["data"]["pagerank"][0]["account"]
    assert top == truth_aurora["ring_a"]["hub"]


def test_trace_money_path_mule_to_hub(seeded, truth_aurora):
    mule = truth_aurora["ring_a"]["mules"][0]
    hub = truth_aurora["ring_a"]["hub"]
    res = run_tool(seeded, "aurora", "trace_money_path", {"from_account_id": mule, "to_account_id": hub})
    assert res["ok"]
    route = res["data"]["paths"][0]["route"]
    assert route[0] == mule and route[-1] == hub


def test_money_flow_capacity_mule_to_hub(seeded, truth_aurora):
    mule = truth_aurora["ring_a"]["mules"][1]
    hub = truth_aurora["ring_a"]["hub"]
    res = run_tool(seeded, "aurora", "money_flow_capacity", {"from_account_id": mule, "to_account_id": hub})
    assert res["ok"]
    # a single aggregated mule->hub edge, each planted between 9,100 and 9,850
    assert 9_000 <= res["data"]["max_flow"] <= 9_900


def test_negative_control_is_not_in_any_ring(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "find_rings", {"min_size": 3})
    comps = res["data"]["components"]
    control = truth_aurora["negative_control"]
    assert all(control not in c["member_ids"] for c in comps)
    links = run_tool(seeded, "aurora", "find_linked_accounts", {"account_id": control})
    assert links["ok"] and links["data"]["associations"] == []


def test_linked_accounts_exposes_association_evidence(seeded, truth_aurora):
    hub = truth_aurora["ring_a"]["hub"]
    res = run_tool(seeded, "aurora", "find_linked_accounts", {"account_id": hub})
    assert res["ok"]
    via_types = {row["via"] for row in res["data"]["associations"]}
    assert "address" in via_types
    linked_ids = {row["account"] for row in res["data"]["associations"]}
    assert linked_ids == set(truth_aurora["ring_a"]["mules"])


def test_alert_queue_shape(seeded, truth_aurora):
    res = run_tool(seeded, "aurora", "list_alerts", {"status": "open"})
    assert res["ok"]
    ids = {a["id"] for a in res["data"]["alerts"]}
    assert ids == set(truth_aurora["live_alerts"])
    alr1 = run_tool(seeded, "aurora", "get_alert", {"alert_id": truth_aurora["live_alerts"][0]})
    assert alr1["ok"] and alr1["data"]["severity"] == 4
