"""Strategy kernel — the model of *what to trade*.

Holds everything a strategy is built from: indicators, entry models, exit
tactics, sizing and the strategy roster itself. Deliberately free of backtest
harness and live-session concerns so the same classes run under both
(see docs/v2/01-architecture.md §3.1).
"""
