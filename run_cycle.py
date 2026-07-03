"""Entry-proposal cycle. Run once/day (cron). For each underlying in the
watchlist: LLM proposes -> rails evaluate -> contract selection -> execution
-> log -> Discord. NOT YET RUN against a live paper account — needs
ALPACA_API_KEY/ALPACA_SECRET_KEY/ANTHROPIC_API_KEY/DISCORD_WEBHOOK_URL in
.env first (see SETUP.md). The deterministic logic underneath (risk_rails,
contracts, exits) is unit-tested; this orchestration script is the
integration layer that still needs a real paper-account dry run.
"""

from __future__ import annotations

import logging

from harness import decision_log, notify
from harness.alpaca_glue import make_client
from harness.contracts import select_covered_call, select_csp
from harness.env import allowed_strategies, config, universe
from harness.positions import build_account_state
from harness.proposer import propose
from harness.risk_rails import active_rails, evaluate_proposal

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optionsagent.run_cycle")


def run() -> None:
    cfg = config()
    phase = cfg.get("phase", "wheel")
    strategies = allowed_strategies()
    cycle_id = decision_log.record_cycle_start(phase)
    log.info("cycle %s starting, phase=%s, strategies=%s", cycle_id, phase, strategies)

    client = make_client()
    account_raw = client.account_state()
    positions_raw = client.list_positions()
    account = build_account_state(account_raw=account_raw, positions_raw=positions_raw)

    bundle = {
        "phase": phase,
        "allowed_strategies": strategies,
        "watchlist": [{"underlying": sym, "context": {}} for sym in universe()],
    }
    proposals = propose(bundle)
    log.info("cycle %s: %d proposal(s) from proposer", cycle_id, len(proposals))

    rails = active_rails()
    wheel_cfg = cfg["wheel"]

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
        }

        if not decision.approved:
            record["outcome"] = "vetoed"
            decision_log.record(record)
            notify.trade_vetoed(
                underlying=proposal.underlying, strategy_type=proposal.strategy_type, reason=decision.reason
            )
            continue

        chain = client.option_chain(proposal.underlying)

        if proposal.strategy_type == "csp":
            quote = select_csp(
                chain,
                delta_min=wheel_cfg["csp_delta_min"],
                delta_max=wheel_cfg["csp_delta_max"],
                dte_min=wheel_cfg["csp_dte_min"],
                dte_max=wheel_cfg["csp_dte_max"],
                score_min=wheel_cfg["score_min"],
            )
        elif proposal.strategy_type == "covered_call":
            shares_position = next(
                (
                    p
                    for p in positions_raw
                    if p["symbol"] == proposal.underlying and p["asset_class"].lower() == "us_equity"
                ),
                None,
            )
            if shares_position is None or shares_position["qty"] < 100:
                record["outcome"] = "skipped_no_shares_owned"
                decision_log.record(record)
                continue
            cost_basis = shares_position["cost_basis"] / shares_position["qty"]
            quote = select_covered_call(
                chain,
                cost_basis=cost_basis,
                delta_min=wheel_cfg["covered_call_delta_min"],
                delta_max=wheel_cfg["covered_call_delta_max"],
                dte_min=wheel_cfg["covered_call_dte_min"],
                dte_max=wheel_cfg["covered_call_dte_max"],
                score_min=wheel_cfg["score_min"],
            )
        else:
            record["outcome"] = f"strategy_type {proposal.strategy_type} not yet implemented (phase 1 = wheel only)"
            decision_log.record(record)
            continue

        if quote is None:
            record["outcome"] = "no_contract_matched_criteria"
            decision_log.record(record)
            notify.trade_vetoed(
                underlying=proposal.underlying,
                strategy_type=proposal.strategy_type,
                reason="no contract in the chain matched the delta/DTE criteria",
            )
            continue

        contracts = max(1, int(decision.position_cap_usd / (quote.strike * 100)))
        record["contract"] = quote.__dict__
        record["contracts"] = contracts
        record["outcome"] = "executed"
        decision_log.record(record)
        notify.trade_opened(
            underlying=proposal.underlying,
            strategy_type=proposal.strategy_type,
            strike=quote.strike,
            dte=quote.dte,
            credit_or_debit=quote.bid,
            thesis=proposal.thesis,
        )

    log.info("cycle %s complete", cycle_id)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:  # a crashed cycle must be visible, not silent
        logging.exception("cycle failed")
        notify.error(f"run_cycle crashed: {e}")
        raise
