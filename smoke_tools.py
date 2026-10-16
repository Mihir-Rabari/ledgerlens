from ledgerlens.graph import connection
from ledgerlens.tools import run_tool
import json
import pathlib

truth = json.loads(pathlib.Path("tests/fixtures/planted_aurora.json").read_text())
conn = connection()
tenant = "aurora"


def call(name, args):
    res = run_tool(conn, tenant, name, args)
    mark = "OK " if res["ok"] else "ERR"
    print(f"{mark} {name}: {res.get('summary') or res.get('error', {}).get('detail', '')[:160]}")
    return res


hub = truth["ring_a"]["hub"]
mule1 = truth["ring_a"]["mules"][0]
sender3 = truth["ring_b"]["senders"][2]
rb_hub = truth["ring_b"]["hub"]

r = call("get_account_profile", {"account_id": hub})
r = call("get_account_activity", {"account_id": hub})
r = call("find_linked_accounts", {"account_id": mule1})
rings = call("find_rings", {"min_size": 3})
if rings["ok"]:
    comps = rings["data"]["components"]
    print("   components:", [(c["size"], c["internal_transfer_edges"]) for c in comps])
    big = max(comps, key=lambda c: c["size"])
    rank = call("rank_ring_accounts", {"member_ids": big["member_ids"]})
    if rank["ok"]:
        print("   pagerank top:", [(x["account"], round(x["score"], 3)) for x in rank["data"]["pagerank"][:3]])
    call("component_graph", {"member_ids": big["member_ids"]})

call("trace_money_path", {"from_account_id": mule1, "to_account_id": hub})
call("money_flow_capacity", {"from_account_id": truth["ring_a"]["mules"][1], "to_account_id": hub})
call("explain_connection", {"account_id_a": mule1, "account_id_b": hub})
call("explain_connection", {"account_id_a": mule1, "account_id_b": truth["negative_control"]})
mem = call("search_memory", {"text": "device ring"})
if mem["ok"]:
    print("   findings:", [f["id"] for f in mem["data"]["findings"]],
          "cases:", [c["id"] for c in mem["data"]["cases"]])
call("get_playbook", {"playbook": "shared-device"})
alerts = call("list_alerts", {"status": "open"})
if alerts["ok"]:
    print("   open alerts:", [a["id"] for a in alerts["data"]["alerts"]])
call("get_alert", {"alert_id": truth["live_alerts"][0]})
call("get_case", {"case_id": truth["past_case"]})
call("graph_stats", {})
call("get_account_profile", {"account_id": "AUR-ACC-9999"})
call("trace_money_path", {"from_account_id": mule1, "to_account_id": truth["negative_control"]})
