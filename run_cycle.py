"""Entry-proposal cycle. Run once/day (cron). For each underlying in the
watchlist: LLM proposes -> rails evaluate -> contract selection -> execution
-> structure registry -> log -> Discord.

All 8 strategies live (operator 2026-07-03). Every executed structure is
recorded in data/structures.jsonl so the exit sweep knows what each flat
Alpaca position actually is.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from harness import chain_capture, decision_log, market_context, notify, structures
from harness.alpaca_glue import make_client
from harness.contracts import (
    select_covered_call,
    select_credit_spread,
    select_csp,
    select_debit_spread,
    select_long_option,
    select_straddle,
)
from harness.env import allowed_strategies, config, universe
from harness.execution import (
    confirm_fill,
    execute_covered_call_on_owned_shares,
    execute_covered_straddle,
    execute_credit_spread,
    execute_csp,
    execute_debit_spread,
    execute_long_option,
    execute_long_straddle,
)
from harness.exits import LONG_TYPES
from harness.positions import build_account_state
from harness.proposer import propose_report
from harness.risk_rails import (
    active_rails,
    apply_opened_position,
    RESEARCH_RULES_MAX_CLOSE_COST_X,
    active_credit_spread_gate,
    credit_spread_gate_decision,
    research_rules_missing_cap,
    evaluate_proposal,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_cycle")


def _expiry_iso(dte: int) -> str:
    return (date.today() + timedelta(days=dte)).isoformat()


def _owned_share_lots(positions_raw: list[dict], underlying: str) -> tuple[int, float | None]:
    """Returns (lots_of_100_owned, per_share_cost_basis or None)."""
    pos = next(
        (
            p
            for p in positions_raw
            if p["symbol"] == underlying and p["asset_class"].lower() == "us_equity" and p["qty"] >= 100
        ),
        None,
    )
    if pos is None:
        return 0, None
    return int(pos["qty"]) // 100, pos["cost_basis"] / pos["qty"]


def _select_and_price(proposal, chain, cfg, positions_raw, conviction_size_frac):
    """Deterministic contract selection + per-contract capital requirement.
    Returns (legs_for_registry, executor_kwargs, executor_fn, per_contract_usd,
    entry_net, max_contracts_clamp, skip_reason). skip_reason is set when the
    strategy can't be built (no contract match / prerequisites missing)."""
    wheel = cfg["wheel"]
    spreads = cfg["spreads"]
    longs = cfg["long_options"]
    strads = cfg["straddles"]
    st = proposal.strategy_type

    if st == "csp":
        q = select_csp(
            chain,
            delta_min=wheel["csp_delta_min"],
            delta_max=wheel["csp_delta_max"],
            dte_min=wheel["csp_dte_min"],
            dte_max=wheel["csp_dte_max"],
            score_min=wheel["score_min"],
        )
        if q is None:
            return None, None, None, 0, 0, None, "no_contract_matched_criteria"
        legs = [structures.Leg(q.symbol, "short", "put", q.strike, _expiry_iso(q.dte))]
        return legs, {"quote": q}, execute_csp, q.strike * 100, q.bid, None, None

    if st == "covered_call":
        lots, cost_basis = _owned_share_lots(positions_raw, proposal.underlying)
        if lots < 1:
            return None, None, None, 0, 0, None, "skipped_no_shares_owned"
        q = select_covered_call(
            chain,
            cost_basis=cost_basis,
            delta_min=wheel["covered_call_delta_min"],
            delta_max=wheel["covered_call_delta_max"],
            dte_min=wheel["covered_call_dte_min"],
            dte_max=wheel["covered_call_dte_max"],
            score_min=wheel["score_min"],
        )
        if q is None:
            return None, None, None, 0, 0, None, "no_contract_matched_criteria"
        legs = [structures.Leg(q.symbol, "short", "call", q.strike, _expiry_iso(q.dte))]
        return legs, {"quote": q}, execute_covered_call_on_owned_shares, q.strike * 100, q.bid, lots, None

    if st in ("credit_spread", "debit_spread"):
        if proposal.direction not in ("bullish", "bearish"):
            return None, None, None, 0, 0, None, f"direction {proposal.direction!r} unusable for a vertical spread"
        select = select_credit_spread if st == "credit_spread" else select_debit_spread
        kwargs = dict(
            direction=proposal.direction,
            delta_min=spreads["short_delta_min"] if st == "credit_spread" else longs["delta_min"],
            delta_max=spreads["short_delta_max"] if st == "credit_spread" else longs["delta_max"],
            dte_min=spreads["dte_min"],
            dte_max=spreads["dte_max"],
            max_width=spreads["max_width_usd"],
        )
        if st == "credit_spread" and active_credit_spread_gate() == "research_rules":
            # let the picker prefer pairs the liquidity floor will accept
            kwargs["max_unwind_ratio"] = RESEARCH_RULES_MAX_CLOSE_COST_X
        pair = select(chain, **kwargs)
        if pair is None:
            return None, None, None, 0, 0, None, "no_spread_matched_criteria"
        legs = [
            structures.Leg(pair.short.symbol, "short", pair.short.right, pair.short.strike, _expiry_iso(pair.short.dte)),
            structures.Leg(pair.long.symbol, "long", pair.long.right, pair.long.strike, _expiry_iso(pair.long.dte)),
        ]
        if st == "credit_spread":
            overfit_ok, overfit_reason = credit_spread_gate_decision(
                underlying=proposal.underlying,
                direction=proposal.direction,
                width=pair.width,
                net_credit=pair.net_credit,
                # what the exit sweep would pay to unwind on these same quotes
                close_cost_now=pair.short.ask - pair.long.bid,
            )
            if not overfit_ok:
                return None, None, None, 0, 0, None, overfit_reason
            return legs, {"legs": pair}, execute_credit_spread, pair.width * 100, pair.net_credit, None, None
        net_debit = pair.long.ask - pair.short.bid
        return legs, {"legs": pair}, execute_debit_spread, net_debit * 100, net_debit, None, None

    if st in ("long_call", "long_put"):
        right = "call" if st == "long_call" else "put"
        # conviction scales the delta target within the band: floor conviction
        # -> delta_min (cheaper, more leverage needed to pay off), max
        # conviction -> delta_max (more intrinsic, higher win odds)
        target = longs["delta_min"] + (longs["delta_max"] - longs["delta_min"]) * conviction_size_frac
        q = select_long_option(
            chain,
            right=right,
            target_delta=target,
            delta_min=longs["delta_min"],
            delta_max=longs["delta_max"],
            dte_min=longs["dte_min"],
            dte_max=longs["dte_max"],
        )
        if q is None:
            return None, None, None, 0, 0, None, "no_contract_matched_criteria"
        legs = [structures.Leg(q.symbol, "long", right, q.strike, _expiry_iso(q.dte))]
        return legs, {"quote": q}, execute_long_option, q.ask * 100, q.ask, None, None

    if st == "long_straddle":
        pair = select_straddle(
            chain, dte_min=strads["dte_min"], dte_max=strads["dte_max"], dte_target=strads["dte_target"]
        )
        if pair is None:
            return None, None, None, 0, 0, None, "no_straddle_matched_criteria"
        legs = [
            structures.Leg(pair.call.symbol, "long", "call", pair.call.strike, _expiry_iso(pair.call.dte)),
            structures.Leg(pair.put.symbol, "long", "put", pair.put.strike, _expiry_iso(pair.put.dte)),
        ]
        return legs, {"legs": pair}, execute_long_straddle, pair.total_debit * 100, pair.total_debit, None, None

    if st == "covered_straddle":
        lots, _ = _owned_share_lots(positions_raw, proposal.underlying)
        if lots < 1:
            return None, None, None, 0, 0, None, "skipped_no_shares_owned"
        pair = select_straddle(
            chain, dte_min=strads["dte_min"], dte_max=strads["dte_max"], dte_target=strads["dte_target"]
        )
        if pair is None:
            return None, None, None, 0, 0, None, "no_straddle_matched_criteria"
        legs = [
            structures.Leg(pair.call.symbol, "short", "call", pair.call.strike, _expiry_iso(pair.call.dte)),
            structures.Leg(pair.put.symbol, "short", "put", pair.put.strike, _expiry_iso(pair.put.dte)),
        ]
        # capital = full cash backing for the short put (ARCHITECTURE.md:
        # stricter than Alpaca's margin math, by decision). The short call is
        # covered by the owned shares, already counted in exposure.
        return legs, {"legs": pair}, execute_covered_straddle, pair.put.strike * 100, pair.total_credit, lots, None

    return None, None, None, 0, 0, None, f"strategy_type {st!r} not implemented"


def proposal_skip_reason(
    underlying: str, *, universe: list[str], seen_this_cycle: set[str], open_underlyings: set[str]
) -> str | None:
    """One position per underlying, universe names only (2026-09-01 review:
    the proposer accepts any string and any count, and nothing consulted the
    open-structure registry, so 'CCL bullish' twice or an off-list NVDA each
    got its own full-size budget)."""
    sym = str(underlying or "").strip().upper()
    if sym not in {s.upper() for s in universe}:
        return "skipped_not_in_universe"
    if sym in seen_this_cycle:
        return "skipped_duplicate_underlying_this_cycle"
    if sym in open_underlyings:
        return "skipped_underlying_already_open"
    return None


def run() -> None:
    cfg = config()
    phase = cfg.get("phase", "all")
    strategies = allowed_strategies()
    # Config sanity guard, FIRST — before any broker/LLM construction. Entry
    # DTE windows must sit ABOVE each family's mandatory close threshold.
    for section, key in (
        ("wheel", "csp_dte_min"),
        ("wheel", "covered_call_dte_min"),
        ("spreads", "dte_min"),
        ("long_options", "dte_min"),
        ("straddles", "dte_min"),
    ):
        if cfg[section][key] <= cfg[section]["dte_close"]:
            raise ValueError(
                f"config error: {section}.{key} ({cfg[section][key]}) must be > "
                f"{section}.dte_close ({cfg[section]['dte_close']})"
            )

    cycle_id = decision_log.record_cycle_start(phase)
    log.info("cycle %s starting, phase=%s, strategies=%s", cycle_id, phase, strategies)

    client = make_client()
    account_raw = client.account_state()
    positions_raw = client.list_positions()
    account = build_account_state(account_raw=account_raw, positions_raw=positions_raw)

    syms = universe()

    # Backtesting prerequisite (always on, fail-open): persist today's full
    # chain snapshots (quotes+IV+greeks) before anything else can crash.
    try:
        counts = chain_capture.capture_universe(client, syms)
        failed = [s for s, n in counts.items() if n < 0]
        log.info("chain snapshots captured: %s", counts)
        if failed:
            notify.error(f"chain snapshot capture failed for {', '.join(failed)} (cycle continues)")
    except Exception:
        log.exception("chain snapshot capture failed entirely (fail-open, cycle continues)")

    context_by_symbol = market_context.build_context(client, syms)
    n_with_data = sum(1 for c in context_by_symbol.values() if market_context.has_data(c))
    log.info(
        "cycle %s: market context built for %d/%d underlyings", cycle_id, n_with_data, len(syms)
    )
    bundle = {
        "phase": phase,
        "allowed_strategies": strategies,
        "watchlist": [{"underlying": sym, "context": context_by_symbol.get(sym, {})} for sym in syms],
    }
    report = propose_report(bundle)
    proposals = report.proposals
    # Journal the CALL, not just its proposals: a dead model and a quiet market
    # both produce zero decisions, and the dashboard must be able to tell them
    # apart (2026-09-01: two "Not logged in" days looked like nothing-to-trade).
    decision_log.record(report.as_journal_row(cycle_id, decision_log.now_iso()))
    log.info(
        "cycle %s: %d proposal(s) from proposer (%s/%s ok=%s attempts=%d %.1fs%s)",
        cycle_id, len(proposals), report.provider, report.model, report.ok,
        report.attempts, report.latency_s, f" error={report.error}" if report.error else "",
    )

    rails = active_rails()
    gate_mode = active_credit_spread_gate()
    # Log the thresholds every decision below is judged against, not just the
    # verdict: a row that says "vetoed" or "executed" without the cap and gate
    # that produced it cannot be audited later (fleet lesson, 2026-08).
    judged_against = {
        "credit_spread_gate": gate_mode,
        "max_position_abs_usd": rails.max_position_abs_usd,
        "max_concurrent_positions": rails.max_concurrent_positions,
        "spread_rules": {
            "short_delta": [cfg["spreads"]["short_delta_min"], cfg["spreads"]["short_delta_max"]],
            "dte": [cfg["spreads"]["dte_min"], cfg["spreads"]["dte_max"]],
            "max_width_usd": cfg["spreads"]["max_width_usd"],
        },
    }
    log.info("cycle %s: judged against %s", cycle_id, judged_against)

    if research_rules_missing_cap(gate_mode, rails):
        msg = (
            "research_rules gate is on but OA_MAX_POSITION_USD is unset or unparsable — "
            "refusing to size against raw buying power; no trades this cycle"
        )
        log.error("cycle %s: %s", cycle_id, msg)
        decision_log.record({
            "kind": "cycle_refused", "cycle_id": cycle_id, "ts": decision_log.now_iso(),
            "reason": msg, "judged_against": judged_against,
        })
        notify.error(msg)
        return

    open_underlyings = {s.underlying.upper() for s in structures.load_open()}
    seen_this_cycle: set[str] = set()

    for proposal in proposals:
        decision_id = decision_log.new_decision_id()
        decision = evaluate_proposal(proposal, account, allowed_strategies=strategies, rails=rails)
        record = {
            "kind": "decision",
            "cycle_id": cycle_id,
            "decision_id": decision_id,
            "ts": decision_log.now_iso(),
            "proposal": proposal.__dict__,
            "rail_decision": decision.__dict__,
            "judged_against": judged_against,
        }

        skip_reason = proposal_skip_reason(
            proposal.underlying, universe=syms, seen_this_cycle=seen_this_cycle,
            open_underlyings=open_underlyings,
        )
        seen_this_cycle.add(proposal.underlying.upper())
        if skip_reason is not None:
            record["outcome"] = skip_reason
            decision_log.record(record)
            notify.trade_vetoed(
                underlying=proposal.underlying, strategy_type=proposal.strategy_type, reason=skip_reason
            )
            continue

        if not decision.approved:
            record["outcome"] = "vetoed"
            decision_log.record(record)
            notify.trade_vetoed(
                underlying=proposal.underlying, strategy_type=proposal.strategy_type, reason=decision.reason
            )
            continue

        chain = client.option_chain(proposal.underlying)
        legs, exec_kwargs, executor, per_contract_usd, entry_net, lots_clamp, skip = _select_and_price(
            proposal, chain, cfg, positions_raw, decision.size_frac
        )
        if skip is not None:
            record["outcome"] = skip
            decision_log.record(record)
            notify.trade_vetoed(
                underlying=proposal.underlying, strategy_type=proposal.strategy_type, reason=skip
            )
            continue

        if per_contract_usd <= 0:
            record["outcome"] = "skipped_nonpositive_per_contract_capital"
            decision_log.record(record)
            continue
        contracts = int(decision.position_cap_usd / per_contract_usd)
        if lots_clamp is not None:
            contracts = min(contracts, lots_clamp)  # never short more calls than owned lots
        record["legs"] = [leg.__dict__ for leg in legs]
        record["contracts"] = contracts
        record["per_contract_usd"] = per_contract_usd
        if contracts < 1:
            record["outcome"] = "skipped_cap_below_one_contract"
            decision_log.record(record)
            notify.trade_vetoed(
                underlying=proposal.underlying,
                strategy_type=proposal.strategy_type,
                reason=f"position cap ${decision.position_cap_usd:,.0f} is below one "
                f"contract's requirement ${per_contract_usd:,.0f} — skipped",
            )
            continue

        result = executor(client, contracts=contracts, decision_id=decision_id, **exec_kwargs)

        record["orders"] = result.orders
        if result.success:
            # Book what FILLED, not what was asked for. One-order structures
            # (every spread, CSP, long option) are confirmed here; the two-order
            # covered strategies keep their own in-executor confirmation.
            if len(result.orders) == 1 and isinstance(result.orders[0], dict) and result.orders[0].get("id"):
                fill = confirm_fill(client, result.orders[0]["id"], requested=contracts)
                record["fill"] = fill
                if fill["filled_qty"] < 1:
                    record["outcome"] = "unfilled_cancelled"
                    decision_log.record(record)
                    notify.trade_vetoed(
                        underlying=proposal.underlying,
                        strategy_type=proposal.strategy_type,
                        reason=f"entry order {fill['status'] or 'unfilled'} after the confirmation "
                        f"window; remainder cancelled, nothing opened",
                    )
                    continue
                if fill["filled_qty"] < contracts:
                    log.warning(
                        "%s: partial fill %d/%d, remainder cancelled; booking %d",
                        proposal.underlying, fill["filled_qty"], contracts, fill["filled_qty"],
                    )
                contracts = int(fill["filled_qty"])
                record["contracts"] = contracts
            record["outcome"] = "executed"
            structures.record_opened(
                structures.Structure(
                    structure_id=decision_id,
                    underlying=proposal.underlying,
                    strategy_type=proposal.strategy_type,
                    contracts=contracts,
                    entry_net=abs(entry_net),
                    legs=legs,
                    opened_ts=decision_log.now_iso(),
                    order_ids=[o["id"] for o in result.orders if isinstance(o, dict) and o.get("id")],
                )
            )
            account = apply_opened_position(
                account,
                underlying=proposal.underlying,
                collateral_usd=contracts * per_contract_usd,
                positions_opened=len(legs),
            )
            notify.trade_opened(
                underlying=proposal.underlying,
                strategy_type=proposal.strategy_type,
                strike=legs[0].strike,
                dte=(date.fromisoformat(legs[0].expiry) - date.today()).days,
                # notify prints Credit for >= 0, Debit for < 0: long
                # structures pay a debit, short premium collects a credit
                credit_or_debit=(-entry_net if proposal.strategy_type in LONG_TYPES else entry_net),
                thesis=proposal.thesis,
            )
        else:
            record["outcome"] = f"execution_failed: {result.reason}"
            notify.error(
                f"{proposal.underlying} {proposal.strategy_type} execution failed: {result.reason}"
            )
        decision_log.record(record)

    log.info("cycle %s complete", cycle_id)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:  # a crashed cycle must be visible, not silent
        logging.exception("cycle failed")
        notify.error(f"run_cycle crashed: {e}")
        raise
