"""Platform auth: users, sessions and the login audit trail — all in FalkorDB.

LedgerLens has no sidecar database anywhere in the stack: credentials and
the login audit trail live in the same FalkorDB server as the tenant
graphs, in a dedicated ``ledgerlens_platform`` graph. A login is a graph
event — ``(:User)-[:PERFORMED]->(:LoginEvent)`` — so the audit story the
product tells about investigations ("every claim is a node or an edge")
extends to who signed in and when.

Passwords are scrypt-hashed with per-user salts (stdlib ``hashlib``);
session tokens are HMAC-SHA256 signed payloads (stdlib ``hmac``) carried
in an HttpOnly cookie. No external auth dependency ships in the venv.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import UTC, datetime

from .config import CONFIG

AUTH_GRAPH = "ledgerlens_platform"
SESSION_COOKIE = "ll_session"
SESSION_TTL = 7 * 24 * 3600
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.@-]{3,40}$")
_SECRET_FIELDS = ("password_hash", "salt")


class AuthError(Exception):
    """Raised on any auth failure; carries the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rows(result) -> list[dict]:
    """Flatten a FalkorDB result into [{col: value}]."""
    names = []
    for c in (result.header or []):
        if isinstance(c, (tuple, list)) and len(c) >= 2:
            names.append(str(c[1]))
        elif hasattr(c, "name"):
            names.append(str(c.name))
        else:
            names.append(str(c))
    out = []
    for row in result.result_set:
        item = {}
        for name, value in zip(names, row, strict=False):
            if hasattr(value, "properties"):
                item[name] = dict(value.properties)
            else:
                item[name] = value
        out.append(item)
    return out


# ── password hashing (stdlib scrypt) ─────────────────────────────────


def hash_password(password: str) -> tuple[str, str]:
    """Return (salt_hex, hash_hex) for a password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    expected = bytes.fromhex(hash_hex)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return hmac.compare_digest(digest, expected)


# ── signed session tokens (stdlib HMAC) ───────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def mint_token(user: dict) -> str:
    payload = _b64(json.dumps({
        "uid": user["id"],
        "username": user["username"],
        "name": user.get("full_name", ""),
        "tenant": user["tenant"],
        "role": user["role"],
        "exp": int(time.time()) + SESSION_TTL,
    }).encode())
    sig = _b64(hmac.new(CONFIG.auth_secret.encode(), payload.encode(),
                        hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> dict | None:
    """Verify signature + expiry; return the payload dict or None."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected = hmac.new(CONFIG.auth_secret.encode(), payload_b64.encode(),
                            hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig_b64), expected):
            return None
        payload = json.loads(_unb64(payload_b64))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


# ── user store (FalkorDB `ledgerlens_platform` graph) ─────────────────


class _EmptyResult:
    """Stand-in for a read against a graph key that does not exist yet."""

    header: list = []
    result_set: list = []


_graph_ready = False


def _write(conn, query: str, params: dict | None = None):
    global _graph_ready
    result = conn.system_graph().query(query, params or {})
    _graph_ready = True  # any write creates the platform graph key
    return result


def _read(conn, query: str, params: dict | None = None):
    global _graph_ready
    # GRAPH.RO_QUERY on a missing key raises in FalkorDB; treat as empty.
    if _graph_ready:
        return conn.system_graph().ro_query(query, params or {})
    if AUTH_GRAPH in conn.client.execute_command("GRAPH.LIST"):
        _graph_ready = True
        return conn.system_graph().ro_query(query, params or {})
    return _EmptyResult()


def _public(user: dict) -> dict:
    return {k: v for k, v in user.items() if k not in _SECRET_FIELDS}


def get_user(conn, username: str) -> dict | None:
    rows = _rows(_read(conn,
                      "MATCH (u:User {username: $username}) RETURN u",
                      {"username": username}))
    return _public(rows[0]["u"]) if rows else None


def create_user(conn, *, username: str, password: str, full_name: str,
                tenant: str, role: str = "analyst") -> dict:
    if not _USERNAME_RE.match(username):
        raise AuthError("username must be 3-40 chars: letters, digits, _ . @ -")
    if len(password) < 8:
        raise AuthError("password must be at least 8 characters", 400)
    if role not in ("analyst", "admin"):
        raise AuthError("role must be analyst or admin", 400)
    if tenant not in conn.list_tenants():
        raise AuthError(f"unknown tenant: {tenant}", 400)
    if get_user(conn, username):
        raise AuthError("username already taken", 409)

    user_id = f"usr_{secrets.token_hex(5)}"
    salt_hex, hash_hex = hash_password(password)
    _write(conn,
           "CREATE (u:User {id: $id, username: $username, full_name: $full_name, "
           "tenant: $tenant, role: $role, password_hash: $hash, salt: $salt, "
           "created_at: $at, last_login_at: ''})",
           {"id": user_id, "username": username, "full_name": full_name,
            "tenant": tenant, "role": role, "hash": hash_hex, "salt": salt_hex,
            "at": _now()})
    return get_user(conn, username) or {}


def _record_login_event(conn, username: str, user_id: str | None, *, ok: bool) -> None:
    """Every login attempt is a node in the audit graph — even failures."""
    event_id = f"login_{secrets.token_hex(6)}"
    at = _now()
    params = {"eid": event_id, "at": at, "ok": ok, "username": username}
    if user_id:
        _write(conn,
               "MATCH (u:User {id: $uid}) "
               "CREATE (u)-[:PERFORMED]->(:LoginEvent {id: $eid, at: $at, ok: $ok, username: $username})",
               {**params, "uid": user_id})
    else:
        _write(conn,
               "CREATE (:LoginEvent {id: $eid, at: $at, ok: $ok, username: $username})",
               params)


def record_signin(conn, user: dict) -> None:
    """Audit a non-interactive sign-in (e.g. right after registration)."""
    _record_login_event(conn, user["username"], user["id"], ok=True)


def verify_login(conn, username: str, password: str) -> dict:
    user_row = _rows(_read(conn,
                           "MATCH (u:User {username: $username}) RETURN u",
                           {"username": username}))
    stored = user_row[0]["u"] if user_row else None
    password_ok = bool(stored) and verify_password(
        password, stored.get("salt", ""), stored.get("password_hash", ""))

    user = _public(stored) if stored else None
    _record_login_event(conn, username,
                        (user or {}).get("id"), ok=password_ok)
    if not (password_ok and user is not None):
        raise AuthError("invalid username or password", 401)

    _write(conn,
           "MATCH (u:User {id: $uid}) SET u.last_login_at = $at",
           {"uid": user["id"], "at": _now()})
    user["last_login_at"] = _now()
    return user


def list_login_events(conn, username: str, limit: int = 10) -> list[dict]:
    rows = _rows(_read(conn,
                       "MATCH (e:LoginEvent {username: $username}) "
                       "RETURN e.at AS at, e.ok AS ok ORDER BY e.at DESC LIMIT $limit",
                       {"username": username, "limit": limit}))
    for r in rows:
        r["ok"] = bool(r.get("ok"))
    return rows


def seed_default_users(conn) -> list[str]:
    """Idempotent demo accounts so a fresh seed always has working logins."""
    seeded: list[str] = []
    accounts = [
        {"username": "admin@ledgerlens.io", "password": "ledgerlens123",
         "full_name": "Platform Admin", "tenant": "aurora", "role": "admin"},
    ]
    for tenant in conn.list_tenants():
        accounts.append({
            "username": f"analyst@{tenant}",
            "password": "ledgerlens123",
            "full_name": f"{tenant.capitalize()} Analyst",
            "tenant": tenant, "role": "analyst",
        })
    for acct in accounts:
        existing = get_user(conn, acct["username"])
        if existing:
            continue
        create_user(conn, **acct)
        seeded.append(acct["username"])
    return seeded


# ── HTTP layer helpers (used by service.py) ───────────────────────────


def session_payload(token: str) -> dict | None:
    """Verify a session cookie value; return the payload dict or None."""
    return read_token(token) if token else None
