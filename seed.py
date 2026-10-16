"""Synthetic, deterministic multi-tenant seed data for LedgerLens.

Every bank is one isolated FalkorDB graph. All data is synthetic (hackathon
rule 6: public, synthetic, or your own data only) and generated from a fixed
random seed, so any two runs produce the same world up to timestamps.

Each tenant gets:
- a normal population of persons, accounts, devices, addresses, merchants
- two planted fraud structures (an obvious shared-device ring and a subtle
  structuring funnel), plus one negative-control alert that is high value but
  legitimately isolated — the investigator must be able to *not* act
- a closed case from a past session whose findings match today's alerts, so
  cross-session memory changes the outcome of a live investigation
- procedural playbooks (the investigation SOPs the agents must follow)

Graph design notes:
- ``TRANSFER`` edges are a per-account-pair aggregation of the underlying
  Transaction records (amount = summed flow, count = number of txns). Keeping
  at most one edge per ordered pair gives algorithms a simple adjacency —
  ``algo.maxFlow`` requires exactly that — while Transaction nodes keep the
  full audit trail.
- ``LINKED_TO`` edges are the association projection: an edge exists when two
  accounts share a device, an address, or an owner. Component detection and
  community detection run over these plus TRANSFER.

Timestamps are relative to seed time so "learned N days ago" reads correctly
whenever the demo runs. Planted ground truth is written to
``tests/fixtures/planted_<tenant>.json`` so tests can assert that the tools
find exactly what was planted.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledgerlens.graph import connection, tenant_graph_name
from ledgerlens.model import BANKS, PLAYBOOKS

SEED = 20261016
STRUCTURE_THRESHOLD = 10_000
FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"

FIRST_NAMES = [
    "Aisha", "Bilal", "Chen", "Dara", "Emeka", "Farah", "Gustav", "Hana", "Ilya", "Juno",
    "Kiran", "Lena", "Mateo", "Nadia", "Omar", "Priya", "Quentin", "Rosa", "Samir", "Tara",
    "Umar", "Vera", "Wei", "Xenia", "Yara", "Zaid", "Anika", "Boyd", "Cleo", "Dmitri",
]
LAST_NAMES = [
    "Okafor", "Tanaka", "Petrov", "Silva", "Haddad", "Ng", "Muller", "Costa", "Iyer", "Kim",
    "Novak", "Reyes", "Anders", "Bello", "Chowdhury", "Duarte", "Egede", "Farsi", "Gomes", "Haq",
]
COMPANY_WORDS = ["Meridian", "Harbour", "Zenith", "Corvus", "Pacific", "Delta", "Orbit", "Lantern", "Anchor", "Beacon"]
COMPANY_KINDS = ["Trade Ltd", "Holdings", "Imports LLC", "Ventures", "Logistics", "Consulting"]
CITIES = ["Harbour Point", "Northgate", "Kilimani", "Riverside", "Old Town", "Silverwood"]
MERCHANTS = [
    ("Nova Casino", "gambling"), ("Sunrise Electronics", "electronics"), ("Orbit Travel", "travel"),
    ("Cedar Furniture", "home"), ("Bluewater Charters", "travel"), ("Gilded Pawn", "pawn"),
    ("Freshmart Grocery", "grocery"), ("Metro Telecom", "utilities"), ("Ivy Prep School", "education"),
    ("Grand Horizon Hotel", "hospitality"), ("QuickWire Remit", "remittance"), ("Silverline Jewelers", "luxury"),
]
CHANNELS = ["mobile", "web", "branch", "atm"]


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class BankBuilder:
    """Builds one bank's world in memory; the loader pushes it into FalkorDB."""

    def __init__(self, bank: dict, rng: random.Random, now: datetime):
        self.bank = bank
        self.slug = bank["slug"]
        self.code = bank["code"]
        self.rng = rng
        self.now = now
        self.currency = {"AUR": "SGD", "NMB": "CAD", "VRD": "KES"}[bank["code"]]
        self.persons: list[dict] = []
        self.accounts: list[dict] = []
        self.ownerships: list[tuple[str, str]] = []
        self.devices: list[dict] = []
        self.accesses: list[tuple[str, str]] = []
        self.addresses: list[dict] = []
        self.lives_at: list[tuple[str, str]] = []
        self.registered_at: list[tuple[str, str]] = []
        self.merchants: list[dict] = []
        self.txns: list[dict] = []
        self.transfers: list[dict] = []
        self._transfer_index: dict[tuple[str, str], int] = {}
        self.linked: list[dict] = []
        self._link_keys: set[tuple] = set()
        self.alerts: list[dict] = []
        self.cases: list[dict] = []
        self.case_alerts: list[tuple[str, str]] = []
        self.case_accounts: list[tuple[str, str]] = []
        self.findings: list[dict] = []
        self.finding_targets: list[tuple[str, str, str]] = []
        self.case_findings: list[tuple[str, str]] = []
        self.sessions: list[dict] = []
        self.handoffs: list[tuple[str, str]] = []
        self.actions: list[dict] = []

    # -- id helpers ---------------------------------------------------------
    def acc(self, n: int) -> str:
        return f"{self.code}-ACC-{n:04d}"

    def per(self, n: int) -> str:
        return f"{self.code}-PER-{n:04d}"

    def dev(self, n: int) -> str:
        return f"DEV-{self.code}-{n:04d}"

    def adr(self, n: int) -> str:
        return f"{self.code}-ADR-{n:04d}"

    def mer(self, n: int) -> str:
        return f"{self.code}-MER-{n:03d}"

    def txn(self, n: int) -> str:
        return f"{self.code}-TXN-{n:05d}"

    def alr(self, n: int) -> str:
        return f"{self.code}-ALR-{n:03d}"

    def cas(self, n: int) -> str:
        return f"{self.code}-CAS-{n:03d}"

    def fin(self, n: int) -> str:
        return f"{self.code}-FIN-{n:03d}"

    def ses(self, n: int) -> str:
        return f"{self.code}-SES-{n:03d}"

    def act(self, n: int) -> str:
        return f"{self.code}-ACT-{n:03d}"

    def name(self) -> str:
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"

    def company(self) -> str:
        return f"{self.rng.choice(COMPANY_WORDS)} {self.rng.choice(COMPANY_KINDS)}"

    def days_ago(self, days: float) -> datetime:
        return self.now - timedelta(days=days)

    # -- helpers ------------------------------------------------------------
    def _new_account(self, n: int, owner: str | None, kind: str = "checking", name: str | None = None) -> dict:
        acc = {
            "id": self.acc(n),
            "name": name or self.name(),
            "kind": kind,
            "opened_at": iso(self.days_ago(self.rng.randint(60, 1500))),
            "kyc_risk": round(self.rng.uniform(0.05, 0.55), 2),
            "status": "active",
            "home_country": self.bank["country"],
        }
        self.accounts.append(acc)
        if owner:
            self.ownerships.append((owner, acc["id"]))
        return acc

    def _account_of_person(self, person_id: str) -> str:
        for owner, acc in self.ownerships:
            if owner == person_id:
                return acc
        raise KeyError(person_id)

    def _link_pair(self, a: str, b: str, via: str, via_id: str) -> None:
        if a == b:
            return
        key = (min(a, b), max(a, b), via, via_id)
        if key in self._link_keys:
            return
        self._link_keys.add(key)
        self.linked.append({"a": min(a, b), "b": max(a, b), "via": via, "via_id": via_id})

    def _txn(self, n: int, src: str, dst: str | None, amount: float, at: datetime,
             merchant: str | None = None, channel: str | None = None) -> dict:
        t = {
            "id": self.txn(n),
            "at": iso(at),
            "amount": amount,
            "currency": self.currency,
            "channel": channel or self.rng.choice(CHANNELS),
            "from": src,
            "to": dst,
            "merchant": merchant,
        }
        self.txns.append(t)
        if dst:
            pair = (src, dst)
            if pair in self._transfer_index:
                idx = self._transfer_index[pair]
                edge = self.transfers[idx]
                edge["amount"] = round(edge["amount"] + amount, 2)
                edge["count"] += 1
                if at.isoformat(timespec="seconds") > edge["at"]:
                    edge["at"] = iso(at)
            else:
                self._transfer_index[pair] = len(self.transfers)
                self.transfers.append({
                    "from": src, "to": dst, "txn_id": t["id"], "amount": amount,
                    "at": iso(at), "channel": t["channel"], "count": 1,
                })
        return t

    # -- population ---------------------------------------------------------
    def build_population(self, n_persons: int = 190, n_extra_accounts: int = 40) -> None:
        for i in range(1, n_persons + 1):
            self.persons.append({
                "id": self.per(i),
                "name": self.name(),
                "email": f"user{i}.{self.slug}@mail-{self.slug}.example",
                "phone": f"+1-555-{self.rng.randint(100, 999)}-{self.rng.randint(1000, 9999)}",
            })
        acct_n = 0
        for p in self.persons:
            self._new_account(acct_n + 1, p["id"], kind="checking")
            acct_n += 1
            if self.rng.random() < 0.22:
                self._new_account(acct_n + 1, p["id"], kind="savings")
                acct_n += 1
        for j in range(n_extra_accounts):
            self._new_account(acct_n + 1 + j, None, kind="business", name=self.company())

        dev_n = 0
        for p in self.persons:
            for _ in range(self.rng.randint(1, 2)):
                dev_n += 1
                fp = self.dev(dev_n)
                self.devices.append({"fp": fp, "os": self.rng.choice(["iOS", "Android", "Windows"])})
                own = self._account_of_person(p["id"])
                self.accesses.append((own, fp))
                if self.rng.random() < 0.06:  # household device sharing (benign association noise)
                    partner = self.rng.choice(self.persons)["id"]
                    if partner != p["id"]:
                        other = self._account_of_person(partner)
                        self.accesses.append((other, fp))
                        self._link_pair(own, other, "device", fp)

        # addresses 1..59 are assignable; 60 and 61 are reserved for the
        # planted ring and the negative-control account so neither picks up
        # accidental association links.
        for i in range(1, 62):
            self.addresses.append({
                "id": self.adr(i),
                "city": self.rng.choice(CITIES),
                "country": self.bank["country"],
            })
        assignable = [a["id"] for a in self.addresses if a["id"] not in (self.adr(60), self.adr(61))]
        for p in self.persons:
            adr = self.rng.choice(assignable)
            self.lives_at.append((p["id"], adr))
            own = self._account_of_person(p["id"])
            self.registered_at.append((own, adr))
            if self.rng.random() < 0.07:  # roommates / family share addresses (benign noise)
                other_person = self.rng.choice(self.persons)["id"]
                if other_person != p["id"]:
                    self.lives_at.append((other_person, adr))
                    other_acc = self._account_of_person(other_person)
                    self.registered_at.append((other_acc, adr))
                    self._link_pair(own, other_acc, "address", adr)

        for i, (mname, mcat) in enumerate(MERCHANTS, 1):
            self.merchants.append({"id": self.mer(i), "name": mname, "category": mcat})

    # -- transactions -------------------------------------------------------
    def build_transactions(self, n_normal: int = 900, n_purchases: int = 220) -> None:
        personal = [a["id"] for a in self.accounts if a["kind"] in ("checking", "savings")]
        txn_n = 0
        for _ in range(n_normal):
            txn_n += 1
            src, dst = self.rng.sample(personal, 2)
            amount = round(self.rng.choice([80, 120, 250, 400, 650, 900, 1400, 2100, 3600, 5200]), 2)
            self._txn(txn_n, src, dst, amount, self.days_ago(self.rng.uniform(0.2, 45)))
        for _ in range(n_purchases):
            txn_n += 1
            src = self.rng.choice(personal)
            mer = self.rng.choice(self.merchants)
            self._txn(txn_n, src, None, round(self.rng.uniform(15, 2400), 2),
                      self.days_ago(self.rng.uniform(0.2, 45)), merchant=mer["id"])

    # -- planted fraud structures ------------------------------------------
    def plant_rings(self) -> None:
        # ---- ring A: shared devices + beneficiary funnel into one hub
        hub = self._new_account(950, None, kind="business", name=self.company())
        hub["kyc_risk"] = 0.72
        mules: list[dict] = []
        for i in range(1, 7):
            m = self._new_account(950 + 10 + i, None, kind="checking")
            m["kyc_risk"] = round(self.rng.uniform(0.6, 0.9), 2)
            mules.append(m)
        r1, r2 = self.dev(990), self.dev(991)
        self.devices.append({"fp": r1, "os": "Android"})
        self.devices.append({"fp": r2, "os": "Windows"})
        even_mules = mules[0::2]
        odd_mules = mules[1::2]
        for group, fp in ((even_mules, r1), (odd_mules, r2)):
            for m in group:
                self.accesses.append((m["id"], fp))
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    self._link_pair(group[i]["id"], group[j]["id"], "device", fp)
        ring_adr = self.adr(60)
        ring_members = [hub] + mules
        for m in ring_members:
            self.registered_at.append((m["id"], ring_adr))
        for i in range(len(ring_members)):
            for j in range(i + 1, len(ring_members)):
                self._link_pair(ring_members[i]["id"], ring_members[j]["id"], "address", ring_adr)
        for day, m in enumerate(mules):
            self._txn(10_000 + day, m["id"], hub["id"], round(self.rng.uniform(9_100, 9_850), 2),
                      self.days_ago(1 + day * 0.5), channel="web")
        self._txn(10_050, hub["id"], self.acc(1), round(self.rng.uniform(38_000, 52_000), 2),
                  self.days_ago(0.5), channel="web")
        org1, org2 = self.per(191), self.per(192)
        self.persons.extend([
            {"id": org1, "name": self.name(), "email": f"org1.{self.slug}@mail-{self.slug}.example", "phone": "+1-555-010-0001"},
            {"id": org2, "name": self.name(), "email": f"org2.{self.slug}@mail-{self.slug}.example", "phone": "+1-555-010-0002"},
        ])
        for i, m in enumerate(mules[:3]):
            self.ownerships.append(((org1, org2)[i % 2], m["id"]))
            other = next(x["id"] for x in mules[3:])
            self._link_pair(m["id"], other, "owner", (org1, org2)[i % 2])
        self.ring_a = {"hub": hub, "mules": mules, "devices": [r1, r2], "address": ring_adr, "organizers": [org1, org2]}

        # ---- ring B: subtle structuring funnel (weaker association signal)
        hub2 = self._new_account(970, None, kind="business", name=self.company())
        hub2["kyc_risk"] = 0.61
        senders: list[dict] = []
        for i in range(1, 6):
            s = self._new_account(970 + 20 + i, None, kind="checking")
            s["kyc_risk"] = round(self.rng.uniform(0.4, 0.7), 2)
            senders.append(s)
        r3 = self.dev(992)
        self.devices.append({"fp": r3, "os": "iOS"})
        for s in senders[:3]:
            self.accesses.append((s["id"], r3))
        for i in range(len(senders[:3])):
            for j in range(i + 1, len(senders[:3])):
                self._link_pair(senders[:3][i]["id"], senders[:3][j]["id"], "device", r3)
        for day, s in enumerate(senders):
            self._txn(10_500 + day, s["id"], hub2["id"], round(self.rng.uniform(9_300, 9_700), 2),
                      self.days_ago(2 + day * 0.4), channel="mobile")
        self.ring_b = {"hub": hub2, "senders": senders, "device": r3}

    # -- negative control ----------------------------------------------------
    def plant_negative_control(self) -> None:
        """A legitimate high-value account: fresh device, fresh address, no rings."""
        account = self._new_account(940, None, kind="savings")
        account["kyc_risk"] = 0.12
        fp = self.dev(940)
        self.devices.append({"fp": fp, "os": "iOS"})
        self.accesses.append((account["id"], fp))
        adr = self.adr(61)
        self.registered_at.append((account["id"], adr))
        dst = next(a["id"] for a in self.accounts if a["kind"] == "checking" and a["id"] != account["id"])
        self._txn(9_999, account["id"], dst, 12_400, self.days_ago(0.8), channel="web")
        self.negative_control = {"account": account["id"], "device": fp}

    # -- alerts, past cases, memory ------------------------------------------
    def build_alerts_and_memory(self) -> None:
        hub, mules = self.ring_a["hub"], self.ring_a["mules"]
        r1, r2 = self.ring_a["devices"]
        sender3 = self.ring_b["senders"][2]
        control = self.negative_control["account"]
        self.alerts.extend([
            {"id": self.alr(1), "kind": "rapid_velocity", "severity": 4, "at": iso(self.days_ago(0.2)),
             "amount": 46_000, "status": "open",
             "summary": f"Burst of 6 inbound transfers to {hub['name']} within 36h.", "account": hub["id"]},
            {"id": self.alr(2), "kind": "shared_device", "severity": 3, "at": iso(self.days_ago(0.4)),
             "amount": 0, "status": "open",
             "summary": f"Device {r1} seen on multiple unrelated accounts.", "account": mules[0]["id"]},
            {"id": self.alr(3), "kind": "structuring", "severity": 4, "at": iso(self.days_ago(0.6)),
             "amount": 47_500, "status": "open",
             "summary": f"Five daily transfers just below {STRUCTURE_THRESHOLD:,} from {sender3['name']}.",
             "account": sender3["id"]},
            {"id": self.alr(4), "kind": "new_beneficiary_high_value", "severity": 2, "at": iso(self.days_ago(0.8)),
             "amount": 12_400, "status": "open",
             "summary": "New beneficiary received a large transfer; no prior relationship.", "account": control},
            {"id": self.alr(90), "kind": "shared_device", "severity": 3, "at": iso(self.days_ago(9)),
             "amount": 0, "status": "closed",
             "summary": f"(Past session) Device {r1} appeared on 4 accounts within 48h.", "account": mules[1]["id"]},
        ])

        # ---- past session (episodic): analyst handed off to investigator
        s1 = {"id": self.ses(1), "agent": "intake-analyst", "started_at": iso(self.days_ago(9))}
        s2 = {"id": self.ses(2), "agent": "case-investigator", "started_at": iso(self.days_ago(8.9))}
        self.sessions.extend([s1, s2])
        self.handoffs.append((s1["id"], s2["id"]))

        case = {
            "id": self.cas(1),
            "title": f"Ghost device ring around {hub['name']}",
            "status": "closed", "severity": 4,
            "opened_at": iso(self.days_ago(9)), "closed_at": iso(self.days_ago(8)),
            "outcome": f"Two mule accounts frozen. Devices {r1} and {r2} linked {len(mules)} accounts feeding "
                       f"{hub['name']}; hub escalated to compliance.",
        }
        self.cases.append(case)
        self.case_alerts.append((case["id"], self.alr(90)))
        self.case_alerts.append((case["id"], self.alr(1)))  # today's alert is the same recurring ring
        for m in mules[:2]:
            self.case_accounts.append((case["id"], m["id"]))
            m["status"] = "frozen"
        self.actions.extend([
            {"id": self.act(1), "kind": "freeze", "at": iso(self.days_ago(8)), "by": "case-investigator",
             "reason": f"Shared device {r1} across ring members", "account": mules[0]["id"]},
            {"id": self.act(2), "kind": "escalate", "at": iso(self.days_ago(8)), "by": "case-investigator",
             "reason": f"Hub {hub['name']} controls the funnel", "account": hub["id"]},
        ])
        f1 = {
            "id": self.fin(1),
            "text": f"Device fingerprint {r1} appeared on 4 accounts within 48h, all sending to {hub['name']}.",
            "at": iso(self.days_ago(8)), "confidence": 0.93, "source": s2["id"],
        }
        f2 = {
            "id": self.fin(2),
            "text": f"{hub['name']} received 46,000 from 5 accounts in 6 days, structured below threshold.",
            "at": iso(self.days_ago(8)), "confidence": 0.88, "source": s2["id"],
        }
        self.findings.extend([f1, f2])
        self.finding_targets.extend([
            (f1["id"], mules[1]["id"], "account"), (f1["id"], hub["id"], "account"), (f1["id"], r1, "device"),
            (f2["id"], hub["id"], "account"),
        ])
        self.case_findings.extend([(case["id"], f1["id"]), (case["id"], f2["id"])])

        case2 = {
            "id": self.cas(2),
            "title": "Retired: payroll vendor duplicate invoice",
            "status": "closed", "severity": 2,
            "opened_at": iso(self.days_ago(24)), "closed_at": iso(self.days_ago(23)),
            "outcome": "Duplicate invoice; vendor corrected. No fraud.",
        }
        self.cases.append(case2)
        self.case_accounts.append((case2["id"], self.acc(2)))
        self.past_case = case

    def planted_truth(self) -> dict:
        return {
            "tenant": self.slug,
            "ring_a": {
                "hub": self.ring_a["hub"]["id"],
                "mules": [m["id"] for m in self.ring_a["mules"]],
                "devices": self.ring_a["devices"],
            },
            "ring_b": {
                "hub": self.ring_b["hub"]["id"],
                "senders": [s["id"] for s in self.ring_b["senders"]],
                "device": self.ring_b["device"],
            },
            "negative_control": self.negative_control["account"],
            "live_alerts": [a["id"] for a in self.alerts if a["status"] == "open"],
            "past_case": self.past_case["id"],
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_bank(conn, tenant: str, b: BankBuilder) -> None:
    g = conn.graph(tenant)

    def run(query: str, params: dict | None = None):
        return g.query(query, params or {})

    def batch_insert(rows: list[dict], template: str, size: int = 500) -> None:
        for i in range(0, len(rows), size):
            run(f"UNWIND $rows AS r {template}", {"rows": rows[i:i + size]})

    run("CREATE (:Bank {name: $name, code: $code, country: $country})",
        {"name": b.bank["name"], "code": b.code, "country": b.bank["country"]})

    batch_insert(b.persons, "CREATE (p:Person {id: r.id, name: r.name, email: r.email, phone: r.phone})")
    batch_insert(b.accounts,
                 "CREATE (a:Account {id: r.id, name: r.name, kind: r.kind, opened_at: r.opened_at, "
                 "kyc_risk: r.kyc_risk, status: r.status, home_country: r.home_country})")
    batch_insert(b.devices, "CREATE (d:Device {fp: r.fp, os: r.os})")
    batch_insert(b.addresses, "CREATE (x:Address {id: r.id, city: r.city, country: r.country})")
    batch_insert(b.merchants, "CREATE (m:Merchant {id: r.id, name: r.name, category: r.category})")

    run("UNWIND $rows AS r MATCH (p:Person {id: r.o}), (a:Account {id: r.a}) CREATE (p)-[:OWNS]->(a)",
        {"rows": [{"o": o, "a": a} for o, a in b.ownerships]})
    run("UNWIND $rows AS r MATCH (a:Account {id: r.a}), (d:Device {fp: r.fp}) CREATE (a)-[:ACCESSED_FROM]->(d)",
        {"rows": [{"a": a, "fp": fp} for a, fp in b.accesses]})
    run("UNWIND $rows AS r MATCH (p:Person {id: r.p}), (x:Address {id: r.x}) CREATE (p)-[:LIVES_AT]->(x)",
        {"rows": [{"p": p, "x": x} for p, x in b.lives_at]})
    run("UNWIND $rows AS r MATCH (a:Account {id: r.a}), (x:Address {id: r.x}) CREATE (a)-[:REGISTERED_AT]->(x)",
        {"rows": [{"a": a, "x": x} for a, x in b.registered_at]})

    batch_insert(b.txns,
                 "CREATE (t:Transaction {id: r.id, at: r.at, amount: r.amount, currency: r.currency, channel: r.channel})")
    run("UNWIND $rows AS r MATCH (t:Transaction {id: r.id}), (a:Account {id: r.a}) CREATE (t)-[:FROM]->(a)",
        {"rows": [{"id": t["id"], "a": t["from"]} for t in b.txns]})
    run("UNWIND $rows AS r MATCH (t:Transaction {id: r.id}), (a:Account {id: r.a}) CREATE (t)-[:TO]->(a)",
        {"rows": [{"id": t["id"], "a": t["to"]} for t in b.txns if t["to"]]})
    run("UNWIND $rows AS r MATCH (t:Transaction {id: r.id}), (m:Merchant {id: r.m}) CREATE (t)-[:AT]->(m)",
        {"rows": [{"id": t["id"], "m": t["merchant"]} for t in b.txns if t["merchant"]]})
    run("UNWIND $rows AS r MATCH (a:Account {id: r.f}), (b:Account {id: r.t}) "
        "CREATE (a)-[:TRANSFER {amount: r.amount, at: r.at, channel: r.channel, count: r.count}]->(b)",
        {"rows": [{"f": t["from"], "t": t["to"], "amount": t["amount"], "at": t["at"],
                   "channel": t["channel"], "count": t["count"]} for t in b.transfers]})
    run("UNWIND $rows AS r MATCH (a:Account {id: r.a}), (b:Account {id: r.b}) "
        "CREATE (a)-[:LINKED_TO {via: r.via, via_id: r.via_id}]->(b)",
        {"rows": b.linked})

    batch_insert(b.alerts,
                 "CREATE (x:Alert {id: r.id, kind: r.kind, severity: r.severity, at: r.at, amount: r.amount, "
                 "status: r.status, summary: r.summary})")
    run("UNWIND $rows AS r MATCH (x:Alert {id: r.id}), (a:Account {id: r.a}) CREATE (x)-[:ABOUT]->(a)",
        {"rows": [{"id": a["id"], "a": a["account"]} for a in b.alerts]})

    batch_insert(b.cases,
                 "CREATE (c:Case {id: r.id, title: r.title, status: r.status, severity: r.severity, "
                 "opened_at: r.opened_at, closed_at: r.closed_at, outcome: r.outcome})")
    run("UNWIND $rows AS r MATCH (c:Case {id: r.c}), (x:Alert {id: r.x}) CREATE (c)-[:INVESTIGATES]->(x)",
        {"rows": [{"c": c, "x": x} for c, x in b.case_alerts]})
    run("UNWIND $rows AS r MATCH (c:Case {id: r.c}), (a:Account {id: r.a}) CREATE (c)-[:INVOLVES]->(a)",
        {"rows": [{"c": c, "a": a} for c, a in b.case_accounts]})

    batch_insert(b.findings,
                 "CREATE (f:Finding {id: r.id, text: r.text, at: r.at, confidence: r.confidence, source: r.source})")
    run("UNWIND $rows AS r MATCH (c:Case {id: r.c}), (f:Finding {id: r.f}) CREATE (c)-[:HAS_FINDING]->(f)",
        {"rows": [{"c": c, "f": f} for c, f in b.case_findings]})
    for fid, target_id, target_kind in b.finding_targets:
        if target_kind == "account":
            run("MATCH (f:Finding {id: $f}), (a:Account {id: $t}) CREATE (f)-[:ABOUT]->(a)", {"f": fid, "t": target_id})
        elif target_kind == "device":
            run("MATCH (f:Finding {id: $f}), (d:Device {fp: $t}) CREATE (f)-[:ABOUT]->(d)", {"f": fid, "t": target_id})

    batch_insert(b.sessions, "CREATE (s:Session {id: r.id, agent: r.agent, started_at: r.started_at})")
    run("UNWIND $rows AS r MATCH (a:Session {id: r.a}), (b:Session {id: r.b}) CREATE (a)-[:HANDS_OFF]->(b)",
        {"rows": [{"a": a, "b": c} for a, c in b.handoffs]})
    run("MATCH (c:Case {id: $c}), (s:Session {id: $s}) CREATE (c)-[:OPENED_IN]->(s)",
        {"c": b.past_case["id"], "s": b.sessions[0]["id"]})
    run("UNWIND $rows AS r MATCH (s:Session {id: r.s}), (f:Finding {id: r.f}) CREATE (s)-[:PRODUCED]->(f)",
        {"rows": [{"s": b.sessions[1]["id"], "f": f["id"]} for f in b.findings]})

    for act in b.actions:
        run("CREATE (x:Action {id: $id, kind: $kind, at: $at, by: $by, reason: $reason})", act)
        run("MATCH (x:Action {id: $id}), (a:Account {id: $acc}) CREATE (x)-[:ACTED_ON]->(a)",
            {"id": act["id"], "acc": act["account"]})
        run("MATCH (x:Action {id: $id}), (c:Case {id: $c}) CREATE (x)-[:RECORDED_IN]->(c)",
            {"id": act["id"], "c": b.past_case["id"]})

    for pb_name, steps in PLAYBOOKS.items():
        run("CREATE (p:Playbook {name: $n, kind: $k})", {"n": pb_name, "k": pb_name})
        for order, st in enumerate(steps, 1):
            run("MATCH (p:Playbook {name: $n}) "
                "CREATE (s:PlaybookStep {order: $o, action: $a, instruction: $i}) CREATE (p)-[:STEP]->(s)",
                {"n": pb_name, "o": order, "a": st["action"], "i": st["instruction"]})

    run("CALL db.idx.fulltext.createNodeIndex('Finding', 'text')")
    run("CALL db.idx.fulltext.createNodeIndex('Case', 'title')")
    run("CALL db.idx.fulltext.createNodeIndex('Case', 'outcome')")
    run("CALL db.idx.fulltext.createNodeIndex('Alert', 'summary')")
    run("CALL db.idx.fulltext.createNodeIndex('Account', 'name')")


def build_bank_data(bank: dict, now: datetime) -> BankBuilder:
    rng = random.Random(SEED + abs(hash(bank["slug"])) % 10_000)
    b = BankBuilder(bank, rng, now)
    b.build_population()
    b.build_transactions()
    b.plant_rings()
    b.plant_negative_control()
    b.build_alerts_and_memory()
    return b


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Seed LedgerLens synthetic bank graphs into FalkorDB")
    parser.add_argument("--tenants", nargs="*", default=[bk["slug"] for bk in BANKS])
    parser.add_argument("--wipe", action="store_true", help="delete existing tenant graphs first")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    conn = connection()
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for bank in BANKS:
        if bank["slug"] not in args.tenants:
            continue
        tenant = bank["slug"]
        gname = tenant_graph_name(tenant)
        if args.wipe:
            try:
                conn.client.execute_command("GRAPH.DELETE", gname)
                print(f"[seed] deleted {gname}")
            except Exception:
                pass
        b = build_bank_data(bank, now)
        load_bank(conn, tenant, b)
        total = conn.graph(tenant).query("MATCH (n) RETURN count(n) AS nodes").result_set[0][0]
        fixture = b.planted_truth()
        (FIXTURES_DIR / f"planted_{tenant}.json").write_text(json.dumps(fixture, indent=2))
        print(f"[seed] {tenant}: {bank['name']} loaded — {len(b.accounts)} accounts, {len(b.txns)} transactions "
              f"({len(b.transfers)} transfer edges), {len(b.linked)} associations, {len(b.alerts)} alerts, "
              f"{len(b.cases)} cases, {total} nodes")


if __name__ == "__main__":
    main()
