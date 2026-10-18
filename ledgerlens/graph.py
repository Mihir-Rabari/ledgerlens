"""FalkorDB connection and per-tenant graph management.

FalkorDB's multigraph topology is the isolation story: every bank is its own
graph (``bank_<slug>``) inside a single server instance. Nothing crosses
tenants because nothing can — the graph key is the boundary, and every tool
call goes through this module which refuses graph names outside the tenant
namespace.
"""

import re
from dataclasses import dataclass

from falkordb import FalkorDB, Graph

from .config import CONFIG

_TENANT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
TENANT_PREFIX = "bank_"
PLATFORM_GRAPH = "ledgerlens_platform"


def tenant_graph_name(tenant: str) -> str:
    """Validate and expand a tenant slug into its FalkorDB graph key."""
    if not _TENANT_RE.match(tenant):
        raise ValueError(f"invalid tenant slug: {tenant!r}")
    return TENANT_PREFIX + tenant


@dataclass
class LensConnection:
    """Owns the FalkorDB client; hands out per-tenant graph handles."""

    client: FalkorDB

    @classmethod
    def connect(cls) -> "LensConnection":
        password = CONFIG.falkordb_password or None
        username = CONFIG.falkordb_username or None
        client = FalkorDB(
            host=CONFIG.falkordb_host,
            port=CONFIG.falkordb_port,
            username=username,
            password=password,
        )
        return cls(client=client)

    def graph(self, tenant: str) -> Graph:
        return self.client.select_graph(tenant_graph_name(tenant))

    def list_tenants(self) -> list[str]:
        graphs = self.client.execute_command("GRAPH.LIST")
        return sorted(g[len(TENANT_PREFIX) :] for g in graphs if g.startswith(TENANT_PREFIX))

    def system_graph(self) -> Graph:
        """Platform graph (users + login audit), outside the tenant namespace."""
        return self.client.select_graph(PLATFORM_GRAPH)

    def read(self, tenant: str, query: str, params: dict | None = None):
        """Read path: always GRAPH.RO_QUERY. Tools must never need more than this."""
        return self.graph(tenant).ro_query(query, params or {})

    def write(self, tenant: str, query: str, params: dict | None = None):
        """Write path: deliberate mutations only (case/memory/action tools)."""
        return self.graph(tenant).query(query, params or {})


_CONNECTION: LensConnection | None = None


def connection() -> LensConnection:
    global _CONNECTION
    if _CONNECTION is None:
        _CONNECTION = LensConnection.connect()
    return _CONNECTION
