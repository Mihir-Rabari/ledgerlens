"""Per-tenant isolation: FalkorDB multigraph means one graph per bank — prove it."""

from ledgerlens.tools import run_tool


def test_aurora_entities_do_not_exist_in_nimbus(seeded, truth_aurora):
    ring_ids = [truth_aurora["ring_a"]["hub"]] + truth_aurora["ring_a"]["mules"]
    from ledgerlens.tools import validate_entities

    rows = validate_entities(seeded, "nimbus", ring_ids)
    assert rows, "validate_entities returned nothing"
    assert all(not (r["is_account"] or r["is_person"] or r["is_device"]) for r in rows)


def test_aurora_profile_is_unknown_entity_in_nimbus(seeded, truth_aurora):
    res = run_tool(seeded, "nimbus", "get_account_profile", {"account_id": truth_aurora["ring_a"]["hub"]})
    assert not res["ok"]
    assert res["error"]["shape"] == "unknown_entity"


def test_alert_queues_are_disjoint(seeded):
    aurora = run_tool(seeded, "aurora", "list_alerts", {"status": "open"})["data"]["alerts"]
    nimbus = run_tool(seeded, "nimbus", "list_alerts", {"status": "open"})["data"]["alerts"]
    verdant = run_tool(seeded, "verdant", "list_alerts", {"status": "open"})["data"]["alerts"]
    a_ids = {a["id"] for a in aurora}
    n_ids = {a["id"] for a in nimbus}
    v_ids = {a["id"] for a in verdant}
    assert a_ids and n_ids and v_ids
    assert a_ids.isdisjoint(n_ids) and a_ids.isdisjoint(v_ids) and n_ids.isdisjoint(v_ids)
    assert all(i.startswith("AUR-") for i in a_ids)
    assert all(i.startswith("NMB-") for i in n_ids)
    assert all(i.startswith("VRD-") for i in v_ids)


def test_tenant_graphs_are_separate_counts(seeded):
    stats = {}
    for tenant in ("aurora", "nimbus", "verdant"):
        res = run_tool(seeded, tenant, "graph_stats", {})
        stats[tenant] = sum(n["count"] for n in res["data"]["nodes"])
    assert stats["aurora"] > 1_500 and stats["nimbus"] > 1_500 and stats["verdant"] > 1_500
    # all seeded within the same magnitude but distinct graphs
    assert stats["aurora"] != stats["nimbus"] or stats["aurora"] != stats["verdant"]
