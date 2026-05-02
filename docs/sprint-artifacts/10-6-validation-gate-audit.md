# Story 10.6 — Strategy validation-gate audit

**Effort:** S
**Phase:** 3 — Live trading P0 blockers
**Findings:** D7#2 (strategies bypassing rule engine — partial)
**Date:** 2026-05-01
**Predecessor:** 10.5c `ZmqExecutionClient`

## Goal

Confirm every strategy in `services/trading-engine/src/strategies/`
submits orders through the Nautilus seam that the live execution
client (story 10.5c) wraps with `ValidatedZmqAdapter` (rule engine +
10.4 atomic exposure gate). No strategy may construct a bracket
`OrderList` and call `submit_order_list` outside the documented seam.

## Architectural seam

```
Strategy.on_bar
    └── _submit_bracket_for_entry          (BracketStrategyMixin)
        └── _submit_bracket_order          (BaseStrategy — pure args build)
            └── _submit_bracket_via_factory (BaseStrategy — single seam)
                ├── self.order_factory.bracket(**args)
                └── self.submit_order_list(order_list)
                            │
                            └── Nautilus exec engine
                                    └── ZmqExecutionClient._submit_order
                                            └── dispatch_submit_order
                                                    └── ValidatedZmqAdapter.send_order_and_wait
                                                            ├── OrderValidator (rule engine)
                                                            └── ExposureReservation (10.4 atomic gate)
                                                                    └── ZMQ → mt5-bridge
```

`order_factory.bracket(...)` and `submit_order_list(...)` exist in
exactly **one** place in the codebase: `base_strategy.py:_submit_bracket_via_factory`.
That is the auditable seam.

## Per-strategy audit

| Strategy file | Submission path | Validates? |
|---|---|---|
| `supertrend.py` | `_submit_bracket_for_entry` (mixin) → seam | ✓ |
| `donchian_breakout.py` | `_submit_bracket_for_entry` (mixin) → seam | ✓ |
| `rsi_mean_reversion.py` | `_submit_bracket_for_entry` (mixin) → seam | ✓ |
| `bollinger_mean_reversion.py` | `_submit_bracket_for_entry` (mixin) → seam | ✓ |
| `orb.py` | `_submit_bracket_for_entry` (mixin) → seam | ✓ |
| `ma_crossover.py` | `self.order_factory.market(...)` + `self.submit_order(order)` | ✓ (Nautilus seam routes through validated client) |
| `base_strategy.py` | Defines the seam; default `_go_long` / `_go_short` use `submit_order` | ✓ |

**Result:** zero bypasses. Every concrete strategy lands in either the
bracket seam or the simpler `submit_order` seam — both of which the
live execution client (`ZmqExecutionClient._submit_order`) intercepts.

## Regression guard

`tests/unit/test_strategy_validation_gate.py` (8 tests) parses each
file under `src/strategies/` with `ast.walk` and fails if:

- any file other than `base_strategy.py` calls
  `self.order_factory.bracket(...)`,
- any file other than `base_strategy.py` calls
  `submit_order_list(...)`,
- any strategy reaches into Nautilus internals
  (`exec_engine.*`, `_send`, `send_order_and_wait`),
- any "expected bracket" strategy stops using
  `_submit_bracket_for_entry`,
- any "expected non-bracket" strategy stops using `self.submit_order`.

Adding a new strategy that needs bracket semantics goes through the
helper; adding one with a genuine reason to bypass requires an
explicit code-review decision and an updated `SEAM_FILES` allowlist.

## Out of scope

- Backtest validation: `BacktestExecClient` does not run
  `ValidatedZmqAdapter` today; the rule engine still runs via the
  `PropFirmComplianceActor` post-fill (reactive). Story 10.5d may
  align live and backtest validation; out of scope here.
- New low-level Nautilus APIs added in future versions of
  `nautilus_trader` — guard them in `TestSubmitOrderUsage` as they
  appear.

## References

- `services/trading-engine/src/strategies/base_strategy.py` — seam.
- `services/trading-engine/src/strategies/bracket_strategy.py` — mixin.
- `services/trading-engine/src/engine/clients/zmq_execution_client.py`
  — live exec client (story 10.5c).
- `services/trading-engine/src/execution/validated_adapter.py` — rule
  engine + atomic exposure gate (Epic 9 P0.12 + story 10.4).
- `tests/unit/test_strategy_validation_gate.py` — regression guard.
- `docs/architecture-review-2026-04-30.md` D7#2.
