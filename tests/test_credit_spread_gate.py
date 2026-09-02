"""The credit-spread gate mode switch (OA_CREDIT_SPREAD_GATE), added 2026-09-01
for the Alpaca hackathon window.

Contract under test:
- default / junk value -> winner_profile (the strict frozen table);
- research_rules -> a picker-approved spread on ANY name passes, but a
  non-positive width or credit still fails closed;
- run_cycle's selector honours the mode and the reason string names it;
- every decision row records the gate mode and the cap it was judged against.
"""

from __future__ import annotations

from harness.contracts import OptionQuote
from harness.env import config
from harness.risk_rails import (
    active_credit_spread_gate,
    credit_spread_gate_decision,
)
from harness.risk_rails import Proposal
from run_cycle import _select_and_price


def test_gate_mode_defaults_to_winner_profile_and_rejects_junk(monkeypatch):
    monkeypatch.delenv("OA_CREDIT_SPREAD_GATE", raising=False)
    assert active_credit_spread_gate() == "winner_profile"
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "open_everything")
    assert active_credit_spread_gate() == "winner_profile"
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", " Research_Rules ")
    assert active_credit_spread_gate() == "research_rules"


def test_winner_profile_mode_still_rejects_a_non_winner_name(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "winner_profile")
    ok, reason = credit_spread_gate_decision(underlying="T", direction="bearish", width=1.0, net_credit=0.30)
    assert ok is False and reason.startswith("overfit_profile")


def test_research_rules_mode_admits_any_name_with_positive_width_and_credit(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    ok, reason = credit_spread_gate_decision(underlying="T", direction="bearish", width=1.0, net_credit=0.30, close_cost_now=0.40)
    assert ok is True
    assert "research_rules" in reason and "bypassed" in reason and "T bearish" in reason


def test_research_rules_mode_fails_closed_on_zero_credit_or_width(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    assert credit_spread_gate_decision(underlying="T", direction="bearish", width=1.0, net_credit=0.0)[0] is False
    assert credit_spread_gate_decision(underlying="T", direction="bearish", width=0.0, net_credit=0.3)[0] is False
    assert credit_spread_gate_decision(underlying="T", direction="bearish", width=float("nan"), net_credit=0.3)[0] is False


def _q(sym, right, strike, delta, bid, ask, underlying="T"):
    return OptionQuote(symbol=sym, underlying=underlying, right=right, strike=strike, dte=35,
                       delta=delta, bid=bid, ask=ask)


def _t_bearish_call_chain():
    # Short 30C at ~0.25 delta, long 32C: width 2.0, credit 0.40-0.10 = 0.30.
    return [
        _q("T30C", "call", 30.0, 0.25, 0.40, 0.45),
        _q("T32C", "call", 32.0, 0.12, 0.10, 0.12),
    ]


def test_run_cycle_selector_rejects_t_bearish_under_winner_profile(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "winner_profile")
    proposal = Proposal(underlying="T", strategy_type="credit_spread", direction="bearish",
                        conviction=0.7, thesis="t")
    result = _select_and_price(proposal, _t_bearish_call_chain(), config(), [], 0.5)
    assert result[0] is None
    assert result[-1].startswith("overfit_profile no historical winner rule for T bearish")


def test_run_cycle_selector_admits_t_bearish_under_research_rules(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    proposal = Proposal(underlying="T", strategy_type="credit_spread", direction="bearish",
                        conviction=0.7, thesis="t")
    legs, kwargs, executor, per_contract_usd, entry_net, lots, skip = _select_and_price(
        proposal, _t_bearish_call_chain(), config(), [], 0.5)
    assert skip is None
    assert executor.__name__ == "execute_credit_spread"
    assert per_contract_usd == 200.0          # width 2.0 x 100 = collateral per contract
    assert abs(entry_net - 0.28) < 1e-9       # conservative credit: short BID 0.40 - long ASK 0.12


def test_research_rules_does_not_loosen_the_contract_picker(monkeypatch):
    """The mode only removes the winner table. A chain with no leg in the
    0.15-0.30 short-delta band still yields no spread."""
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    proposal = Proposal(underlying="T", strategy_type="credit_spread", direction="bearish",
                        conviction=0.7, thesis="t")
    chain = [_q("T30C", "call", 30.0, 0.55, 1.40, 1.45), _q("T32C", "call", 32.0, 0.45, 0.80, 0.85)]
    result = _select_and_price(proposal, chain, config(), [], 0.5)
    assert result[0] is None and result[-1] == "no_spread_matched_criteria"


def test_cap_and_gate_arithmetic_on_a_100k_account(monkeypatch):
    """The reason the cap MUST ship with the gate: without it a 0.62-conviction
    idea on $100k options BP sizes to ~178 contracts of a $2 spread."""
    from harness.risk_rails import AccountState, active_rails, evaluate_proposal

    proposal = Proposal(underlying="T", strategy_type="credit_spread", direction="bearish",
                        conviction=0.62, thesis="t")
    account = AccountState(equity_usd=100_000, available_options_buying_power_usd=100_000,
                           open_positions_count=0, gross_exposure_usd=0.0, underlying_exposure_usd={})

    monkeypatch.delenv("OA_MAX_POSITION_USD", raising=False)
    d = evaluate_proposal(proposal, account, allowed_strategies=["credit_spread"], rails=active_rails())
    assert d.approved and int(d.position_cap_usd / 200.0) == 178

    monkeypatch.setenv("OA_MAX_POSITION_USD", "3000")
    d = evaluate_proposal(proposal, account, allowed_strategies=["credit_spread"], rails=active_rails())
    assert d.approved and d.position_cap_usd == 3000.0 and int(d.position_cap_usd / 200.0) == 15


# -- research_rules liquidity filter (P0-1 from the 2026-09-01 adversarial review) --

def test_research_rules_rejects_a_spread_already_past_its_own_stop(monkeypatch):
    """WBD bull put on the 2026-09-01 snapshot: credit 0.07, unwind-now 0.45.
    The 2x-credit stop would fire on the first confirmed sweep."""
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    ok, reason = credit_spread_gate_decision(
        underlying="WBD", direction="bullish", width=1.0, net_credit=0.07, close_cost_now=0.45)
    assert ok is False and "below minimum" in reason
    ok, reason = credit_spread_gate_decision(
        underlying="VZ", direction="bullish", width=1.0, net_credit=0.11, close_cost_now=0.31)
    assert ok is False and "illiquid" in reason


def test_research_rules_admits_a_liquid_spread_and_names_the_unwind_cost(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    ok, reason = credit_spread_gate_decision(
        underlying="T", direction="bearish", width=1.0, net_credit=0.30, close_cost_now=0.40)
    assert ok is True and "unwind-now 0.40" in reason


def test_research_rules_fails_closed_without_an_unwind_quote(monkeypatch):
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    ok, reason = credit_spread_gate_decision(
        underlying="T", direction="bearish", width=1.0, net_credit=0.30, close_cost_now=None)
    assert ok is False and "missing unwind quote" in reason


def test_selector_passes_unwind_cost_through_to_the_gate(monkeypatch):
    """Short 30C bid 0.40 / ask 0.45, long 32C bid 0.10 / ask 0.12: credit 0.28,
    unwind-now 0.35 -> admitted. Widen the short's ask to 0.60 -> unwind 0.50
    >= 1.5 x 0.28 -> rejected. The gate sees the real quotes, not just width."""
    monkeypatch.setenv("OA_CREDIT_SPREAD_GATE", "research_rules")
    proposal = Proposal(underlying="T", strategy_type="credit_spread", direction="bearish",
                        conviction=0.7, thesis="t")
    ok = _select_and_price(proposal, _t_bearish_call_chain(), config(), [], 0.5)
    assert ok[-1] is None
    wide = [_q("T30C", "call", 30.0, 0.25, 0.40, 0.60), _q("T32C", "call", 32.0, 0.12, 0.10, 0.12)]
    bad = _select_and_price(proposal, wide, config(), [], 0.5)
    assert bad[0] is None and "illiquid" in bad[-1]


# -- gate/cap coupling and per-cycle dedupe (P0-2 / P1-5) ------------------------

def test_research_rules_refuses_without_a_dollar_cap(monkeypatch):
    from harness.risk_rails import active_rails, research_rules_missing_cap
    monkeypatch.delenv("OA_MAX_POSITION_USD", raising=False)
    assert research_rules_missing_cap("research_rules", active_rails()) is True
    monkeypatch.setenv("OA_MAX_POSITION_USD", "3,000")      # the typo case
    assert research_rules_missing_cap("research_rules", active_rails()) is True
    monkeypatch.setenv("OA_MAX_POSITION_USD", "3000")
    assert research_rules_missing_cap("research_rules", active_rails()) is False
    monkeypatch.delenv("OA_MAX_POSITION_USD", raising=False)
    assert research_rules_missing_cap("winner_profile", active_rails()) is False


def test_proposal_skip_reason_dedupes_and_checks_universe_and_open_book():
    from run_cycle import proposal_skip_reason
    uni = ["F", "T", "CCL"]
    assert proposal_skip_reason("NVDA", universe=uni, seen_this_cycle=set(), open_underlyings=set()) == "skipped_not_in_universe"
    assert proposal_skip_reason("ccl", universe=uni, seen_this_cycle={"CCL"}, open_underlyings=set()) == "skipped_duplicate_underlying_this_cycle"
    assert proposal_skip_reason("T", universe=uni, seen_this_cycle=set(), open_underlyings={"T"}) == "skipped_underlying_already_open"
    assert proposal_skip_reason("F", universe=uni, seen_this_cycle={"T"}, open_underlyings={"CCL"}) is None


def test_apply_opened_position_counts_legs_like_the_broker():
    from harness.risk_rails import AccountState, apply_opened_position
    account = AccountState(equity_usd=100_000, available_options_buying_power_usd=100_000,
                           open_positions_count=0, gross_exposure_usd=0.0, underlying_exposure_usd={})
    after = apply_opened_position(account, underlying="T", collateral_usd=3000, positions_opened=2)
    assert after.open_positions_count == 2
    assert after.available_options_buying_power_usd == 97_000
