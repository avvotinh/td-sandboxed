"""Instrument-level market conventions (contract specs).

Single source of truth for the MT5 lot ↔ engine-unit relationship and
per-symbol pip/quote metadata. See :mod:`src.kernel.instruments.contract_specs`.
"""

from src.kernel.instruments.contract_specs import (
    ContractSpec,
    get_contract_spec,
    known_symbols,
)

__all__ = ["ContractSpec", "get_contract_spec", "known_symbols"]
