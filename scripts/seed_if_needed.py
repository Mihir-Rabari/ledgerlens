"""Seed only what is missing — safe to run on every container boot.

Deployments persist the FalkorDB volume, so this script leaves existing
tenant graphs untouched and only seeds banks that have never been created.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import UTC

from ledgerlens.auth import seed_default_users  # noqa: E402
from ledgerlens.graph import connection  # noqa: E402
from ledgerlens.model import BANKS  # noqa: E402
from seed import build_bank_data, load_bank  # noqa: E402


def main() -> None:
    conn = connection()
    existing = set(conn.list_tenants())
    missing = [b for b in BANKS if b["slug"] not in existing]
    if missing:
        from datetime import datetime

        now = datetime.now(UTC)
        for bank in missing:
            b = build_bank_data(bank, now)
            load_bank(conn, bank["slug"], b)
            print(f"[seed-if-needed] seeded {bank['slug']}")
    seeded = seed_default_users(conn)
    if seeded:
        print(f"[seed-if-needed] demo logins ready: {', '.join(seeded)}")
    if not missing and not seeded:
        print("[seed-if-needed] all tenants + demo users present; nothing to do")


if __name__ == "__main__":
    main()
