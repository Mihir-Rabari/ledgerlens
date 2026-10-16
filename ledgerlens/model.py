"""The LedgerLens graph data model.

One graph per bank tenant. This module is the single source of truth for the
node/edge vocabulary, the fraud signal types, and the procedural playbooks.
Docs (GRAPH-MODEL.md, CYPHER.md) are generated from this file plus the tool
registry, so what you read is what runs.

Node labels
-----------
Bank        {name, country, code}
Account     {id, name, kind, opened_at, kyc_risk, status}
Person      {id, name, email, phone}
Device      {fp, os}
Address     {id, city, country}
Merchant    {id, name, category}
Transaction {id, at, amount, currency, channel}
Alert       {id, kind, severity, at, amount, status, summary}
Case        {id, title, status, severity, opened_at, closed_at, outcome}
Finding     {id, text, at, confidence, source}          # semantic memory unit
Playbook    {name, kind}                                 # procedural memory
PlaybookStep{order, action, instruction}
Action      {id, kind, at, by, reason}                   # audit of every decision
Session     {id, agent, started_at}                       # episodic memory frame
Message     {seq, role, at, text}                         # persistent conversation

Edge types
----------
OWNS        Person->Account
ACCESSED_FROM Account->Device
LIVES_AT    Person->Address
REGISTERED_AT Account->Address
AT          Transaction->Merchant
FROM / TO   Transaction->Account
TRANSFER    Account->Account   {txn_id, amount, at, channel}  (projection of FROM/TO)
LINKED_TO   Account->Account   {via: device|address|owner|phone, via_id}  (seeded association)
ABOUT       Alert->Account | Finding->Account | Finding->Person | Finding->Device
INVESTIGATES Case->Alert
INVOLVES    Case->Account
EVIDENCE    Case->Transaction
HAS_FINDING Case->Finding
STEP        Playbook->PlaybookStep
ACTED_ON    Action->Account
RECORDED_IN Action->Case
OPENED_IN   Case->Session
PRODUCED    Session->Finding
RAISED      Session->Alert
HANDS_OFF   Session->Session       (analyst -> investigator handoff)
SAID_IN     Message->Session, session's NEXT Message chain via NEXT
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Node / edge vocabulary (referenced by seed.py, tools.py and docs generation)
# ---------------------------------------------------------------------------

NODE_LABELS = [
    "Bank",
    "Account",
    "Person",
    "Device",
    "Address",
    "Merchant",
    "Transaction",
    "Alert",
    "Case",
    "Finding",
    "Playbook",
    "PlaybookStep",
    "Action",
    "Session",
    "Message",
]

EDGE_TYPES = [
    "OWNS",
    "ACCESSED_FROM",
    "LIVES_AT",
    "REGISTERED_AT",
    "AT",
    "FROM",
    "TO",
    "TRANSFER",
    "LINKED_TO",
    "ABOUT",
    "INVESTIGATES",
    "INVOLVES",
    "EVIDENCE",
    "HAS_FINDING",
    "STEP",
    "ACTED_ON",
    "RECORDED_IN",
    "OPENED_IN",
    "PRODUCED",
    "RAISED",
    "HANDS_OFF",
    "SAID_IN",
    "NEXT",
]

# Alert vocabulary: kind -> human label + the playbook that governs triage
ALERT_KINDS: dict[str, dict[str, str]] = {
    "rapid_velocity": {
        "label": "Rapid transaction velocity",
        "playbook": "rapid-velocity",
        "summary": "Unusual burst of transfers in a short window.",
    },
    "structuring": {
        "label": "Structuring / smurfing pattern",
        "playbook": "structuring",
        "summary": "Repeated transfers just below reporting thresholds.",
    },
    "shared_device": {
        "label": "Shared device across accounts",
        "playbook": "shared-device",
        "summary": "One device fingerprint seen on multiple unrelated accounts.",
    },
    "mule_pattern": {
        "label": "In-and-out (mule) pattern",
        "playbook": "mule-pattern",
        "summary": "Funds arrive and leave the same day, little residue.",
    },
    "new_beneficiary_high_value": {
        "label": "New beneficiary, high value",
        "playbook": "new-beneficiary",
        "summary": "Large transfer to a recently added beneficiary.",
    },
    "device_hopping": {
        "label": "Device hopping",
        "playbook": "device-hopping",
        "summary": "Account accessed from an unusual sequence of new devices.",
    },
}

# Procedural memory: investigation playbooks the agents must follow.
PLAYBOOKS: dict[str, list[dict[str, str]]] = {
    "rapid-velocity": [
        {"action": "profile", "instruction": "Pull the account profile and recent activity window."},
        {"action": "link", "instruction": "Find accounts linked to it through shared devices, addresses and owners."},
        {"action": "rings", "instruction": "Run component detection; note any component the account belongs to."},
        {"action": "money", "instruction": "Trace where the burst funds went; check bottleneck capacity with max-flow."},
        {"action": "memory", "instruction": "Search case memory for prior cases involving these accounts or devices."},
        {"action": "decide", "instruction": "Recommend freeze only if a ring, a hub, or a matching past case is evidenced."},
    ],
    "structuring": [
        {"action": "profile", "instruction": "Pull the account profile and activity window."},
        {"action": "activity", "instruction": "Quantify the just-below-threshold pattern: count, spread, counterparties."},
        {"action": "link", "instruction": "Check linked accounts for the same pattern."},
        {"action": "memory", "instruction": "Search case memory for similar patterns."},
        {"action": "decide", "instruction": "Escalate if the pattern spans multiple accounts; freeze only with a ring."},
    ],
    "shared-device": [
        {"action": "validate", "instruction": "Confirm the device exists and list all accounts using it."},
        {"action": "link", "instruction": "For each linked account, pull owners and recent flags."},
        {"action": "rings", "instruction": "Run component detection over associations and money flow."},
        {"action": "hub", "instruction": "Rank component members by centrality to find the controller."},
        {"action": "memory", "instruction": "Search case memory for the device or linked accounts."},
        {"action": "decide", "instruction": "Freeze the hub account(s) and open a case with the evidence path."},
    ],
    "mule-pattern": [
        {"action": "profile", "instruction": "Pull the account profile."},
        {"action": "money", "instruction": "Trace in and out paths on the same day; compare amounts."},
        {"action": "rings", "instruction": "Run component detection; mules usually sit between two components."},
        {"action": "hub", "instruction": "Identify the upstream source with the highest flow."},
        {"action": "memory", "instruction": "Search case memory for the counterparties."},
        {"action": "decide", "instruction": "Freeze only the pass-through account; escalate the source for review."},
    ],
    "new-beneficiary": [
        {"action": "profile", "instruction": "Pull both accounts' profiles."},
        {"action": "link", "instruction": "Check whether the beneficiary already shares a device, address or owner."},
        {"action": "memory", "instruction": "Search case memory for both parties."},
        {"action": "decide", "instruction": "Clear if isolated and no memory matches; otherwise investigate as a ring."},
    ],
    "device-hopping": [
        {"action": "validate", "instruction": "List the device sequence and its countries/OS."},
        {"action": "link", "instruction": "Check which other accounts those devices touch."},
        {"action": "rings", "instruction": "Run component detection over associations."},
        {"action": "memory", "instruction": "Search case memory for the device fingerprints."},
        {"action": "decide", "instruction": "Escalate if the devices overlap a known ring."},
    ],
}

# Compliance policies (synthetic): the "company knowledge" layer — chunked
# documents in the graph so every agent answer can cite its source.
POLICY_DOCS: list[dict] = [
    {
        "id": "POL-14",
        "title": "Device association monitoring",
        "version": "4.2",
        "effective": "2026-03-01",
        "chunks": [
            "A device fingerprint seen on three or more unrelated accounts within 30 days is a primary ring signal: run component detection before any other check.",
            "Devices previously cited in a closed fraud case are ghost devices: any new account they touch must be treated as ring-adjacent until cleared.",
            "Device hops across three or more device fingerprints inside 14 days on one account warrant a velocity check on its transfer partners.",
        ],
    },
    {
        "id": "POL-22",
        "title": "Structuring detection thresholds",
        "version": "3.1",
        "effective": "2026-06-15",
        "chunks": [
            "The reporting threshold is 10,000 per transfer in bank currency units. Repeated inbound transfers aggregated between 9,000 and 9,900 per account pair inside 7 days indicate structuring.",
            "Structuring across multiple sender accounts into one beneficiary is a ring pattern, not a set of isolated incidents: investigate the beneficiary as the hub.",
            "Single transfers just under threshold with no repetition and no association links are legitimate until memory or associations say otherwise.",
        ],
    },
    {
        "id": "POL-31",
        "title": "Freeze authority and escalation matrix",
        "version": "5.0",
        "effective": "2026-08-01",
        "chunks": [
            "The case investigator may freeze accounts that sit inside an evidenced fraud component (association plus internal money flow). The freeze reason must name the evidence.",
            "When component evidence shows a hub account, freeze it and escalate in the same action: the freeze contains the funnel, the escalation covers customer impact. Escalation without a freeze leaves the funnel open.",
            "Never freeze an account on a single high-value transfer alone: without association links, ring membership, or a matching past case, the correct verdict is no action.",
            "Accounts already frozen from a prior case stay frozen; new ring members joining a recurring structure inherit the escalation path of the original case.",
        ],
    },
]

# Tenant definitions (the seeded banks)
BANKS: list[dict[str, str]] = [
    {"slug": "aurora", "name": "Aurora Trust", "code": "AUR", "country": "Singapore"},
    {"slug": "nimbus", "name": "Nimbus Federal", "code": "NMB", "country": "Canada"},
    {"slug": "verdant", "name": "Verdant Credit Union", "code": "VRD", "country": "Kenya"},
]
