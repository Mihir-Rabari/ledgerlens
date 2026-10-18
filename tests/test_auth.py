"""Auth end-to-end: register → login → HttpOnly session → tenant isolation →
login audit — all against the real FalkorDB (the platform graph IS the user
store) and the real FastAPI app, no mocks except the LLM.

The HTTP layer is what the SPA rides; these tests pin its security contract:
401 without a session, 403 across tenants for analysts, admin-only bench,
and every login attempt landing as a LoginEvent node in the audit graph.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app import app
from ledgerlens import auth
from ledgerlens.graph import connection


@pytest.fixture()
def client():
    """Fresh client per test → isolated cookie jar."""
    return TestClient(app)


@pytest.fixture()
def cleanup_users():
    """Delete any users this test created (plus their login events)."""
    created: list[str] = []
    yield created
    conn = connection()
    for username in created:
        conn.system_graph().query(
            "MATCH (u:User {username: $u}) DETACH DELETE u", {"u": username})
        conn.system_graph().query(
            "MATCH (e:LoginEvent {username: $u}) DELETE e", {"u": username})


def _unique(prefix: str = "qa") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@ledgerlens.io"


def _register(client, created, tenant="aurora", password="qa-password-123"):
    username = _unique()
    r = client.post("/api/auth/register", json={
        "username": username, "password": password,
        "full_name": "QA Analyst", "tenant": tenant})
    created.append(username)
    return username, r


# ── seeded demo users ──────────────────────────────────────────────────


def test_demo_analyst_login_and_me(client):
    r = client.post("/api/auth/login",
                    json={"username": "analyst@aurora", "password": "ledgerlens123"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "analyst"
    assert r.json()["user"]["tenant"] == "aurora"
    # session cookie rides along automatically
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "analyst@aurora"


def test_wrong_password_rejected_and_audited(client, cleanup_users):
    username, r = _register(client, cleanup_users)
    assert r.status_code == 200, r.text
    client.cookies.clear()
    bad = client.post("/api/auth/login",
                      json={"username": username, "password": "wrong-password!"})
    assert bad.status_code == 401
    # the failed attempt is a node in the audit graph
    events = auth.list_login_events(connection(), username)
    assert any(not e["ok"] for e in events), events


# ── route guards ───────────────────────────────────────────────────────


def test_unauthenticated_tenant_route_is_401(client):
    r = client.get("/api/tenants/aurora/alerts")
    assert r.status_code == 401
    r = client.get("/api/tenants/aurora/stats")
    assert r.status_code == 401


def test_analyst_is_locked_to_their_tenant(client, cleanup_users):
    username, r = _register(client, cleanup_users, tenant="aurora")
    assert r.status_code == 200, r.text
    own = client.get("/api/tenants/aurora/stats")
    assert own.status_code == 200
    other = client.get("/api/tenants/nimbus/alerts")
    assert other.status_code == 403
    assert "does not belong" in other.json()["detail"]
    report = client.get("/api/tenants/nimbus/case/NMB-CAS-001")
    assert report.status_code == 403


def test_bench_is_admin_only(client, cleanup_users, monkeypatch):
    username, r = _register(client, cleanup_users, tenant="aurora")
    assert r.status_code == 200
    denied = client.post("/api/bench")
    assert denied.status_code == 403
    assert denied.json()["detail"] == "admin role required"

    client.cookies.clear()
    admin = client.post("/api/auth/login",
                        json={"username": "admin@ledgerlens.io",
                              "password": "ledgerlens123"})
    assert admin.status_code == 200
    # stub the investigations the bench fans out — role gate is what's under test
    monkeypatch.setattr(
        "ledgerlens.service.investigate_alert",
        lambda conn, tenant, alert_id: SimpleNamespace(
            tenant=tenant, alert_id=alert_id, handoff=False, case_id="",
            analyst_session_id="s1", investigator_session_id="s2",
            analyst_final={"verdict": "no_case", "shape": "not_in_graph",
                           "confidence": 0.9, "summary": "stub"},
            investigator_final=None, turns=[]))
    ok = client.post("/api/bench")
    assert ok.status_code == 200, ok.text
    assert ok.json()["parallelism"] >= 1


# ── registration ───────────────────────────────────────────────────────


def test_register_login_logout_lifecycle(client, cleanup_users):
    username, r = _register(client, cleanup_users, tenant="verdant")
    assert r.status_code == 200, r.text
    body = r.json()["user"]
    assert body["tenant"] == "verdant" and body["role"] == "analyst"
    assert "password_hash" not in body and "salt" not in body

    me = client.get("/api/me")
    assert me.status_code == 200  # register logs you in

    out = client.post("/api/auth/logout")
    assert out.status_code == 200
    me2 = client.get("/api/me")
    assert me2.status_code == 401  # cookie is gone


def test_register_validation(client, cleanup_users):
    # duplicate username
    username, r = _register(client, cleanup_users)
    assert r.status_code == 200
    client.cookies.clear()
    dup = client.post("/api/auth/register", json={
        "username": username, "password": "qa-password-123",
        "full_name": "Dup", "tenant": "aurora"})
    assert dup.status_code == 409
    # weak password
    client.cookies.clear()
    weak = client.post("/api/auth/register", json={
        "username": _unique(), "password": "short",
        "full_name": "Weak", "tenant": "aurora"})
    assert weak.status_code == 400
    # unknown tenant
    client.cookies.clear()
    bad_tenant = client.post("/api/auth/register", json={
        "username": _unique(), "password": "qa-password-123",
        "full_name": "Bad", "tenant": "nonexistent-bank"})
    assert bad_tenant.status_code == 400


def test_login_audit_lives_in_the_graph(client, cleanup_users):
    username, r = _register(client, cleanup_users, tenant="aurora")
    assert r.status_code == 200
    client.cookies.clear()
    ok = client.post("/api/auth/login",
                     json={"username": username, "password": "qa-password-123"})
    assert ok.status_code == 200

    conn = connection()
    rows = conn.system_graph().query(
        "MATCH (u:User {username: $u})-[:PERFORMED]->(e:LoginEvent) "
        "RETURN count(e) AS n", {"u": username}).result_set
    assert rows[0][0] >= 2  # the auto-login at register + the explicit one

    my_logins = client.get("/api/me/logins")
    assert my_logins.status_code == 200
    assert any(e["ok"] for e in my_logins.json()["logins"])


def test_admin_can_cross_tenants(client, cleanup_users):
    username, r = _register(client, cleanup_users, tenant="aurora")
    assert r.status_code == 200
    client.cookies.clear()
    admin = client.post("/api/auth/login",
                       json={"username": "admin@ledgerlens.io",
                             "password": "ledgerlens123"})
    assert admin.status_code == 200
    for tenant in ("aurora", "nimbus", "verdant"):
        resp = client.get(f"/api/tenants/{tenant}/stats")
        assert resp.status_code == 200, f"admin blocked from {tenant}"
