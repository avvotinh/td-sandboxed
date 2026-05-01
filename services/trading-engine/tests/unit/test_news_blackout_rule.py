"""Tests for :class:`NewsBlackoutRule` (story 10.8)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.calendar.calendar_models import CalendarEvent, EventIndex
from src.rules.base_rule import RuleAction
from src.rules.types.news_blackout import NewsBlackoutRule


UTC = timezone.utc


def _index(events: list[CalendarEvent]) -> EventIndex:
    return EventIndex(events)


def _event(
    *,
    title: str = "NFP",
    country: str = "USD",
    start: datetime | None = None,
    impact: str = "high",
    symbols: tuple[str, ...] = (),
) -> CalendarEvent:
    return CalendarEvent(
        title=title,
        country=country,
        start=start or datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
        impact=impact,
        symbols=symbols,
    )


def _provider(index: EventIndex | None) -> "callable":
    return lambda: index


# -------------------------------------------------------------------------
# Configuration validation
# -------------------------------------------------------------------------


class TestConstructor:
    def test_default_config(self) -> None:
        rule = NewsBlackoutRule()
        assert rule.config.blackout_minutes_before == 5
        assert rule.config.blackout_minutes_after == 5
        assert rule.config.impact_levels == frozenset({"high"})
        assert rule.config.symbols_filter is None

    def test_custom_window(self) -> None:
        rule = NewsBlackoutRule(
            blackout_minutes_before=10, blackout_minutes_after=15
        )
        assert rule.config.blackout_minutes_before == 10
        assert rule.config.blackout_minutes_after == 15

    def test_negative_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            NewsBlackoutRule(blackout_minutes_before=-1)
        with pytest.raises(ValueError, match="non-negative"):
            NewsBlackoutRule(blackout_minutes_after=-1)

    def test_impact_levels_lowercased(self) -> None:
        rule = NewsBlackoutRule(impact_levels=["HIGH", "Medium"])
        assert rule.config.impact_levels == frozenset({"high", "medium"})

    def test_empty_impact_levels_rejected(self) -> None:
        with pytest.raises(ValueError, match="impact_levels"):
            NewsBlackoutRule(impact_levels=[])

    def test_symbols_filter_uppercased(self) -> None:
        rule = NewsBlackoutRule(symbols_filter=["xauusd", "EURUSD"])
        assert rule.config.symbols_filter == frozenset({"XAUUSD", "EURUSD"})

    def test_blank_symbols_filter_normalised_to_none(self) -> None:
        rule = NewsBlackoutRule(symbols_filter=["", "  "])
        assert rule.config.symbols_filter is None

    def test_yaml_kwargs_ignored(self) -> None:
        # rule_type / action are YAML compatibility fields
        rule = NewsBlackoutRule(rule_type="news_blackout", action="block_trading")
        assert rule.rule_type == "news_blackout"


# -------------------------------------------------------------------------
# validate() — happy path
# -------------------------------------------------------------------------


class TestValidate:
    def test_inside_blackout_blocks(self) -> None:
        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 27, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.BLOCK
        assert "NFP" in (result.message or "")
        assert result.metadata["event_country"] == "USD"

    def test_outside_blackout_allows(self) -> None:
        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 13, 0, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.ALLOW

    def test_unrelated_symbol_allows(self) -> None:
        # Event country=USD, symbol=GBPJPY → no overlap
        index = _index(
            [
                _event(
                    country="USD",
                    start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                )
            ]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "GBPJPY",
            }
        )
        assert result.action is RuleAction.ALLOW

    def test_low_impact_event_allows_by_default(self) -> None:
        index = _index(
            [
                _event(
                    impact="low",
                    start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                )
            ]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.ALLOW

    def test_low_impact_blocked_when_in_filter(self) -> None:
        index = _index(
            [
                _event(
                    impact="low",
                    start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                )
            ]
        )
        rule = NewsBlackoutRule(
            impact_levels=["low", "high"],
            snapshot_provider=_provider(index),
        )
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.BLOCK


# -------------------------------------------------------------------------
# Symbols filter (account-level)
# -------------------------------------------------------------------------


class TestSymbolsFilter:
    def test_account_filter_excludes_symbol(self) -> None:
        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule(
            symbols_filter=["EURUSD"],  # account only watches EURUSD
            snapshot_provider=_provider(index),
        )
        # Order is for XAUUSD — outside the account's watch list
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.ALLOW

    def test_account_filter_includes_symbol(self) -> None:
        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule(
            symbols_filter=["xauusd"],  # case-insensitive
            snapshot_provider=_provider(index),
        )
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.BLOCK


# -------------------------------------------------------------------------
# Fail-open paths
# -------------------------------------------------------------------------


class TestFailOpen:
    def test_no_provider_warns(self) -> None:
        rule = NewsBlackoutRule()  # no snapshot_provider
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.WARN
        assert result.metadata["snapshot_available"] is False

    def test_provider_returns_none_warns(self) -> None:
        rule = NewsBlackoutRule(snapshot_provider=lambda: None)
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.WARN

    def test_empty_index_warns(self) -> None:
        rule = NewsBlackoutRule(snapshot_provider=_provider(_index([])))
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.WARN

    def test_attach_provider_after_construction_works(self) -> None:
        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule()
        # Initially fail-open
        result = rule.validate(
            {"now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC), "symbol": "XAUUSD"}
        )
        assert result.action is RuleAction.WARN

        # Late-bind provider
        rule.attach_snapshot_provider(_provider(index))
        result = rule.validate(
            {"now": datetime(2026, 5, 1, 12, 30, tzinfo=UTC), "symbol": "XAUUSD"}
        )
        assert result.action is RuleAction.BLOCK


# -------------------------------------------------------------------------
# Now resolution
# -------------------------------------------------------------------------


class TestNowResolution:
    def test_naive_now_treated_as_utc(self) -> None:
        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        result = rule.validate(
            {
                "now": datetime(2026, 5, 1, 12, 30),  # naive
                "symbol": "XAUUSD",
            }
        )
        assert result.action is RuleAction.BLOCK

    def test_missing_now_uses_real_clock(self, monkeypatch) -> None:
        # Stub datetime.now in the rule module
        from src.rules.types import news_blackout as nb_module

        fixed = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)

        class _Clock:
            @staticmethod
            def now(tz=None):
                return fixed if tz is None else fixed.astimezone(tz)

        monkeypatch.setattr(nb_module, "datetime", _Clock)

        index = _index(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        result = rule.validate({"symbol": "XAUUSD"})  # no `now`
        assert result.action is RuleAction.BLOCK


# -------------------------------------------------------------------------
# BaseRule protocol surface
# -------------------------------------------------------------------------


class TestProtocolSurface:
    def test_get_current_value_counts_active_events(self) -> None:
        index = _index(
            [
                _event(
                    title="NFP",
                    start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                ),
                _event(
                    title="CPI",
                    start=datetime(2026, 5, 1, 12, 32, tzinfo=UTC),
                ),
            ]
        )
        rule = NewsBlackoutRule(snapshot_provider=_provider(index))
        ctx = {"now": datetime(2026, 5, 1, 12, 31, tzinfo=UTC), "symbol": "XAUUSD"}
        assert rule.get_current_value(ctx) == 2.0

    def test_get_threshold_is_zero(self) -> None:
        rule = NewsBlackoutRule()
        assert rule.get_threshold() == 0.0

    def test_no_warning_thresholds(self) -> None:
        rule = NewsBlackoutRule()
        assert rule.get_warning_thresholds() == []

    def test_name_includes_window(self) -> None:
        rule = NewsBlackoutRule(
            blackout_minutes_before=10, blackout_minutes_after=20
        )
        assert "±10/20m" in rule.name


# -------------------------------------------------------------------------
# Parser registry
# -------------------------------------------------------------------------


class TestParserRegistration:
    def test_news_blackout_loadable_via_rule_parser(self) -> None:
        from src.rules.parser import RuleParser

        parser = RuleParser()
        rule_types = parser.RULE_TYPES
        assert "news_blackout" in rule_types
        # Verify it's our class, not a placeholder
        assert rule_types["news_blackout"] is NewsBlackoutRule
