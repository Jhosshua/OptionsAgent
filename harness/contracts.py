"""Deterministic contract selection — the options-specific rail stage that
stock bots don't need. Given {underlying, strategy_type, direction} from an
approved proposal, picks the actual strike/expiration deterministically.

Covers all strategies (operator 2026-07-03: everything live at once):
wheel (CSP / covered call), credit & debit vertical spreads, long calls/puts,
long straddles, covered straddles. Each selector encodes the delta/DTE
convention sourced in RESEARCH.md.

Wheel scoring formula ported from alpacahq/options-wheel (RESEARCH.md Pass 1):
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


@dataclass(frozen=True)
class SpreadLegs:
    short: OptionQuote
    long: OptionQuote

    @property
    def width(self) -> float:
        return abs(self.short.strike - self.long.strike)

    @property
    def net_credit(self) -> float:
        """Conservative fill assumption: sell the short at bid, buy the long
        at ask. Negative means the combo is a net debit."""
        return self.short.bid - self.long.ask


def select_credit_spread(
    chain: list[OptionQuote],
    *,
    direction: str,  # "bullish" -> put credit spread, "bearish" -> call credit spread
    delta_min: float,
    delta_max: float,
    dte_min: int,
    dte_max: int,
    max_width: float,
) -> SpreadLegs | None:
    """Vertical credit spread: sell a 15-30-delta short leg, buy a further-OTM
    long leg in the SAME expiry, width <= max_width (defined risk). The long
    leg is the nearest strike beyond the short — the tightest defined-risk
    wrapper available. Skips (returns None) if no expiry offers both legs."""
    right = "put" if direction == "bullish" else "call"
    shorts = [
        q
        for q in chain
        if q.right == right
        and delta_min <= abs(q.delta) <= delta_max
        and dte_min <= q.dte <= dte_max
        and q.bid > 0
    ]
    best: SpreadLegs | None = None
    best_score = float("-inf")
    for short in shorts:
        # further OTM: below for puts, above for calls; same expiry (same dte)
        candidates = [
            q
            for q in chain
            if q.right == right
            and q.dte == short.dte
            and 0 < (short.strike - q.strike if right == "put" else q.strike - short.strike) <= max_width
        ]
        if not candidates:
            continue
        long = min(candidates, key=lambda q: abs(q.strike - short.strike))
        legs = SpreadLegs(short=short, long=long)
        if legs.net_credit <= 0:
            continue  # a "credit" spread that costs money is a data-quality red flag
        # rank by credit captured per dollar of defined risk, tempered by the
        # wheel scorer's preference for lower delta / shorter DTE
        score = (legs.net_credit / legs.width) * (1 - abs(short.delta)) * (250 / (short.dte + 5))
        if score > best_score:
            best, best_score = legs, score
    return best


def select_debit_spread(
    chain: list[OptionQuote],
    *,
    direction: str,  # "bullish" -> call debit spread, "bearish" -> put debit spread
    delta_min: float,
    delta_max: float,
    dte_min: int,
    dte_max: int,
    max_width: float,
) -> SpreadLegs | None:
    """Vertical debit spread: buy a 0.50-0.70-delta long leg, sell a
    further-OTM short leg in the same expiry to cut the cost. Note the
    SpreadLegs.net_credit will be negative (it's a debit) — callers size off
    abs(net_credit)."""
    right = "call" if direction == "bullish" else "put"
    longs = [
        q
        for q in chain
        if q.right == right
        and delta_min <= abs(q.delta) <= delta_max
        and dte_min <= q.dte <= dte_max
        and q.ask > 0
    ]
    best: SpreadLegs | None = None
    best_debit_ratio = float("-inf")
    for long in longs:
        candidates = [
            q
            for q in chain
            if q.right == right
            and q.dte == long.dte
            and 0 < (q.strike - long.strike if right == "call" else long.strike - q.strike) <= max_width
            and q.bid > 0
        ]
        if not candidates:
            continue
        short = max(candidates, key=lambda q: abs(q.strike - long.strike))  # widest within cap
        legs = SpreadLegs(short=short, long=long)
        debit = long.ask - short.bid
        if debit <= 0:
            continue
        width = abs(short.strike - long.strike)
        ratio = (width - debit) / debit  # max-gain-to-cost; higher is better
        if ratio > best_debit_ratio:
            best, best_debit_ratio = legs, ratio
    return best


def select_long_option(
    chain: list[OptionQuote],
    *,
    right: str,  # "call" | "put"
    target_delta: float,
    delta_min: float,
    delta_max: float,
    dte_min: int,
    dte_max: int,
) -> OptionQuote | None:
    """Standalone directional long option. RESEARCH.md found no firm entry
    convention (this is inherently thesis-driven) — the deterministic part is
    the band (0.50-0.70 delta, 30-45 DTE) and picking the contract whose
    delta is CLOSEST to the conviction-scaled target within it."""
    candidates = [
        q
        for q in chain
        if q.right == right
        and delta_min <= abs(q.delta) <= delta_max
        and dte_min <= q.dte <= dte_max
        and q.ask > 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda q: (abs(abs(q.delta) - target_delta), q.dte))


@dataclass(frozen=True)
class StraddleLegs:
    call: OptionQuote
    put: OptionQuote

    @property
    def strike(self) -> float:
        return self.call.strike

    @property
    def total_debit(self) -> float:
        """Cost to BUY the straddle (long): both asks."""
        return self.call.ask + self.put.ask

    @property
    def total_credit(self) -> float:
        """Credit for SELLING the straddle (covered): both bids."""
        return self.call.bid + self.put.bid


def select_straddle(
    chain: list[OptionQuote],
    *,
    dte_min: int,
    dte_max: int,
    dte_target: int,
) -> StraddleLegs | None:
    """ATM straddle: the call whose delta is closest to +0.50 (that IS the
    at-the-money definition when no spot price is in hand) in the expiry
    closest to dte_target, paired with the same-strike same-expiry put.
    Used for both long straddles (buy both) and covered straddles (sell
    both) — the leg selection is identical, only the order side differs."""
    calls = [
        q for q in chain if q.right == "call" and dte_min <= q.dte <= dte_max and q.ask > 0
    ]
    if not calls:
        return None
    dtes = sorted({q.dte for q in calls}, key=lambda d: abs(d - dte_target))
    for dte in dtes:
        expiry_calls = [q for q in calls if q.dte == dte]
        atm_call = min(expiry_calls, key=lambda q: abs(abs(q.delta) - 0.50))
        put = next(
            (
                q
                for q in chain
                if q.right == "put" and q.dte == dte and q.strike == atm_call.strike and q.ask > 0
            ),
            None,
        )
        if put is not None:
            return StraddleLegs(call=atm_call, put=put)
    return None
