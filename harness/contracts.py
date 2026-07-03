"""Deterministic contract selection — the options-specific rail stage that
stock bots don't need. Given {underlying, strategy_type, direction} from an
approved proposal, picks the actual strike/expiration deterministically.

Phase 1 (wheel) only: cash-secured put and covered call. Later phases add
credit/debit spreads, long calls/puts, and straddles as their own selectors
in this same module — see ARCHITECTURE.md for each strategy's sourced
delta/DTE convention. Do not add those selectors until their phase is active
(config.json "phase").

Scoring formula ported from alpacahq/options-wheel (RESEARCH.md Pass 1):
    score = (1 - |delta|) * (250 / (DTE + 5)) * (bid / strike)
Higher score favors: lower delta (further OTM, more likely to expire
worthless), shorter DTE (faster theta capture), higher premium yield.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionQuote:
    """One candidate contract from a chain snapshot. `delta` is signed per
    convention (puts negative, calls positive) — callers pass abs(delta) is
    NOT assumed; this module takes the abs value itself."""

    symbol: str          # OCC option symbol
    underlying: str
    right: str            # "call" | "put"
    strike: float
    dte: int
    delta: float
    bid: float
    ask: float


def _score(quote: OptionQuote) -> float:
    if quote.strike <= 0 or quote.bid <= 0:
        return float("-inf")
    return (1 - abs(quote.delta)) * (250 / (quote.dte + 5)) * (quote.bid / quote.strike)


def select_csp(
    chain: list[OptionQuote],
    *,
    delta_min: float,
    delta_max: float,
    dte_min: int,
    dte_max: int,
    score_min: float = 0.0,
) -> OptionQuote | None:
    """Cash-secured put selector. delta_min/max are given as positive
    magnitudes (e.g. 0.20-0.30); put deltas in the chain may be negative,
    this compares on abs(delta)."""
    candidates = [
        q
        for q in chain
        if q.right == "put"
        and delta_min <= abs(q.delta) <= delta_max
        and dte_min <= q.dte <= dte_max
    ]
    if not candidates:
        return None
    scored = [(q, _score(q)) for q in candidates]
    scored = [(q, s) for q, s in scored if s >= score_min]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[1])[0]


def select_covered_call(
    chain: list[OptionQuote],
    *,
    cost_basis: float,
    delta_min: float,
    delta_max: float,
    dte_min: int,
    dte_max: int,
    score_min: float = 0.0,
) -> OptionQuote | None:
    """Covered call selector. Strike floor = cost_basis (wheel-it pattern —
    never sell a call below what the shares cost, to avoid a guaranteed
    realized loss if called away)."""
    candidates = [
        q
        for q in chain
        if q.right == "call"
        and q.strike >= cost_basis
        and delta_min <= abs(q.delta) <= delta_max
        and dte_min <= q.dte <= dte_max
    ]
    if not candidates:
        return None
    scored = [(q, _score(q)) for q in candidates]
    scored = [(q, s) for q, s in scored if s >= score_min]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[1])[0]


def roll_strike_cap(old_strike: float, premium_received: float) -> float:
    """ThetaGang roll-cap convention (RESEARCH.md Pass 1/2): a rolled
    position's new strike is capped at old_strike + premium_received, to
    stop buying-power usage from ratcheting up on repeated rolls."""
    return old_strike + premium_received
