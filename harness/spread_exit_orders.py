"""Durable credit-spread exits: keep day limits working, book only broker fills.

An intent is saved before submission. Lost replies are recovered by client ID;
an ambiguous result blocks another close. Risk exits can replace a profit limit
only after its cancellation is confirmed and any partial fill is accounted for.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from harness import decision_log, notify, structures
from harness.env import ROOT
from harness.execution import TERMINAL_STATUSES, confirm_fill

STATE_PATH = ROOT / "data" / "spread_exit_orders.json"


class SpreadExitOrders:
    def __init__(self, path: Path | None = None):
        self.path = path or STATE_PATH
        self.pending = json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w") as fh:
            json.dump(self.pending, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def _order_id(self, client, record):
        if not record.get("order_id"):
            order = client.find_exit_order(record["client_order_id"], record["search_after"])
            if not order:
                raise RuntimeError("exit submission is unconfirmed; duplicate close blocked")
            record["order_id"] = order["id"]
            self._save()
        return record["order_id"]

    def _settle(self, sid, info) -> bool:
        record = self.pending[sid]
        raw = record["structure"]
        structure = structures.Structure(**{**raw, "legs": [structures.Leg(**leg) for leg in raw["legs"]]})
        qty = int(float(info.get("filled_qty") or 0))
        status = str(info.get("status") or "").lower()
        if qty < 0 or qty > structure.contracts:
            raise ValueError("broker exit fill quantity exceeds tracked spread")
        if status == "filled" and qty != structure.contracts:
            raise ValueError("broker filled status has inconsistent quantity")
        if status not in TERMINAL_STATUSES and qty < structure.contracts:
            return False
        if qty:
            value = info.get("filled_avg_price")
            if value is None or not math.isfinite(float(value)):
                raise ValueError("exit filled but broker fill price unavailable; awaiting reconciliation")
            price = float(value)
            # A single ledger event updates both exposure and realized P&L.
            newly_recorded = structures.record_exit_fill(structure, order_id=record["order_id"],
                contracts=qty, price=price, reason=record["reason"])
            if newly_recorded:
                pnl = round((structure.entry_net - price) * 100 * qty, 2)
                decision_log.record({"kind": "exit", "ts": decision_log.now_iso(),
                    "structure_id": sid, "underlying": structure.underlying,
                    "strategy_type": structure.strategy_type, "reason": record["reason"],
                    "order_id": record["order_id"], "fill": info, "realized_pnl_usd": pnl})
                notify.trade_closed(underlying=structure.underlying, strategy_type=structure.strategy_type,
                    reason=record["reason"], pnl_usd=pnl, contracts=qty,
                    remaining=structure.contracts - qty)
        elif status == "rejected":
            notify.error(f"{structure.underlying}: the broker rejected the closing order. "
                         "The spread remains tracked; the next sweep will recheck it.")
        del self.pending[sid]
        self._save()
        return True

    def recover(self, client):
        """Reconcile tracked exits BEFORE checking for missing option legs."""
        for sid in list(self.pending):
            try:
                oid = self._order_id(client, self.pending[sid])
                self._settle(sid, client.get_order(oid))
            except Exception as exc:
                notify.error(f"{self.pending[sid]['structure']['underlying']}: "
                             f"could not reconcile closing order ({type(exc).__name__}). "
                             "Another close is blocked until the broker confirms its state.")

    def close(self, client, structure, *, net: float, reason: str, profit_target_pct: float):
        sid = structure.structure_id
        profit = reason.startswith("profit target")
        if sid in self.pending:
            previous = self.pending[sid]
            if profit:
                return  # Existing order keeps its place; no duplicate or repeated alert.
            oid = self._order_id(client, previous)
            # A cancellation request is not confirmation. Keep the durable record
            # if the broker still says pending_cancel, or a read fails.
            fill = confirm_fill(client, oid, requested=previous["structure"]["contracts"],
                                tries=1, sleep_s=1)
            if not self._settle(sid, fill):
                notify.error(f"{structure.underlying}: risk exit is waiting for the previous "
                             "order's cancellation confirmation. Duplicate close blocked.")
                return
            structure = next((s for s in structures.load_open() if s.structure_id == sid), None)
            if structure is None:
                return
        limit = round(net, 2)
        if profit:
            # The maximum debit still captures the configured profit, rounded
            # DOWN to a cent so rounding never weakens that target.
            limit = float((Decimal(str(structure.entry_net)) *
                          (1 - Decimal(str(profit_target_pct)))).quantize(Decimal("0.01"), rounding=ROUND_FLOOR))
        if not math.isfinite(limit):
            raise ValueError("invalid spread closing limit")
        decision_id = decision_log.new_decision_id()
        cid = f"oa-exit-{decision_id}"
        record = {"structure": asdict(structure), "reason": reason,
                  "client_order_id": cid, "limit_price": limit,
                  "search_after": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
        self.pending[sid] = record
        self._save()  # Write-ahead intent covers a crash or lost submit response.
        legs = [{"symbol": leg.symbol, "side": "buy" if leg.side == "short" else "sell",
                 "ratio_qty": 1, "position_intent": "buy_to_close" if leg.side == "short" else "sell_to_close"}
                for leg in structure.legs]
        order = client.submit_mleg_order(legs=legs, qty=structure.contracts, limit_price=limit,
                                        decision_id=decision_id, client_order_id=cid)
        record["order_id"] = order["id"]
        self._save()
        fill = confirm_fill(client, order["id"], requested=structure.contracts, cancel_unfilled=False)
        if not self._settle(sid, fill):
            decision_log.record({"kind": "exit_pending", "ts": decision_log.now_iso(),
                "structure_id": sid, "underlying": structure.underlying,
                "order_id": order["id"], "limit_price": limit, "fill": fill, "reason": reason})
            if profit:
                notify.exit_pending(underlying=structure.underlying, contracts=structure.contracts,
                                    limit_price=limit, reason=reason)
            else:
                notify.error(f"{structure.underlying}: risk exit submitted at ${limit:.2f} per share "
                             "but not fully filled. The order remains active and tracked.")
