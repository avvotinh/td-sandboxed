"""Live path — one process, one MT5 account.

Holds everything that only matters when real orders are in flight: the bridge
adapters, order plumbing, session state and reconciliation. The research loop
(kernel + lab) never imports from here (docs/v2/01-architecture.md §3.1).
"""
