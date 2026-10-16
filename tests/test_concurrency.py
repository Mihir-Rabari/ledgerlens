"""High-concurrency reads and writes across tenants (Track 2 key focus)."""

import time
from concurrent.futures import ThreadPoolExecutor

from ledgerlens.tools import run_tool

TENANTS = ("aurora", "nimbus", "verdant")


def _read_task(conn, tenant, i):
    tools = [
        ("find_rings", {"min_size": 3}),
        ("list_alerts", {"status": "open"}),
        ("search_memory", {"text": "device ring"}),
        ("graph_stats", {}),
    ]
    name, args = tools[i % len(tools)]
    res = run_tool(conn, tenant, name, args)
    assert res["ok"], f"{tenant}/{name} failed: {res.get('error')}"
    return tenant, name


def test_concurrent_reads_across_tenants(seeded):
    jobs = []
    for i in range(24):
        jobs.append((TENANTS[i % 3], i))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(_read_task, seeded, tenant, i) for tenant, i in jobs]
        done = [f.result(timeout=120) for f in futures]
    elapsed = time.time() - t0
    assert len(done) == 24
    assert elapsed < 60, f"24 concurrent reads took {elapsed:.1f}s"


def test_concurrent_reads_and_writes(seeded, truth_verdant):
    accounts = [truth_verdant["ring_a"]["hub"]] + truth_verdant["ring_a"]["mules"]

    def write_finding(k):
        res = run_tool(seeded, "verdant", "open_case",
                       {"title": f"Concurrency probe {k}", "severity": 1, "agent": "pytest"})
        assert res["ok"], res
        case_id = res["data"]["case_id"]
        add = run_tool(seeded, "verdant", "add_finding",
                       {"case_id": case_id, "text": f"concurrent finding {k}",
                        "confidence": 0.5, "about_account_ids": [accounts[k % len(accounts)]]})
        assert add["ok"], add
        return case_id

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        reads = [pool.submit(_read_task, seeded, TENANTS[i % 3], i) for i in range(16)]
        writes = [pool.submit(write_finding, k) for k in range(6)]
        [f.result(timeout=120) for f in reads]
        case_ids = [f.result(timeout=120) for f in writes]
    elapsed = time.time() - t0

    assert len(set(case_ids)) == 6, "each concurrent writer must get its own case"
    for cid in case_ids:
        fetched = run_tool(seeded, "verdant", "get_case", {"case_id": cid})
        assert fetched["ok"] and fetched["data"]["findings"]
    assert elapsed < 60, f"mixed load took {elapsed:.1f}s"
