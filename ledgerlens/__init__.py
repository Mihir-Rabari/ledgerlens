"""LedgerLens: a graph-native fraud-ring investigator with persistent case memory.

FalkorDB is not a sidecar here — it is the entire context layer:
the bank data, the investigation memory, the playbooks, the agent handoffs,
and every answer's evidence path all live as one queryable graph per tenant.
"""

__version__ = "0.1.0"
