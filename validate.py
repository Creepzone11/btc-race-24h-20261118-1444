#!/usr/bin/env python3
"""Local replay validator for entry/main.py.

Feeds main.py the published dev window (1440 one-minute CBBTC bars)
as agent-fun/bars-replay/v1 hello/batch/done messages, applies the
market fill model (orders decided on bar k fill at bar k+1 open:
4 bps fee, 2 bps slippage, constant-product impact against that
bar's open depth), and reports net PnL, trades, max drawdown,
first-half / second-half PnL, and determinism (two runs, identical
action logs).

Usage:
  python3 validate.py [--bars PATH] [--bot PATH]
Default bars: the kit dataset at
  ../btc-race-24h-20261118-1444-kit/dataset/bars/CBBTC.ndjson.gz
  (falls back to ./dataset/bars/CBBTC.ndjson.gz)
"""

import argparse
import gzip
import json
import os
import subprocess
import sys

FEE_BPS = 0.0004
SLIP_BPS = 0.0002
START_USDC = 1000.0
QUOTE_UNITS_PER_USDC = 1_000_000


def load_bars(path):
    bars = []
    with gzip.open(path, "rt") as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def run_bot(bot_path, bars):
    """Run main.py as a subprocess over the bars. Returns
    (final_cash, trades, max_dd, equity_at_719, action_log)."""
    hello = {
        "type": "hello",
        "protocol": "agent-fun/bars-replay/v1",
        "seed": "0",
        "warmup_bars": 0,
        "capital": {"quote_units": 1_000_000_000, "quote_scale": 6},
        "symbols": [{
            "symbol": "CBBTC",
            "mint": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",
            "decimals": 8, "qty_scale": 8, "price_scale": 5,
        }],
        "caps": {"max_open_positions": 1, "max_weight_bps": 10000,
                 "max_orders_per_bar": 16},
        "fees": {"min_notional_quote_units": 1000000},
    }
    proc = subprocess.Popen(
        [sys.executable, "-P", "-s", bot_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1)
    proc.stdin.write(json.dumps(hello) + "\n")
    proc.stdin.flush()

    def price(bar, key):
        return int(bar[key]) / 1e5

    def depth_usd(bar, key):
        return int(bar[key][0]) / 1e6

    cash = START_USDC
    qty = 0.0
    trades = 0
    peak = START_USDC
    max_dd = 0.0
    equity_at_719 = None
    action_log = []
    pending = []  # orders decided on previous bar, to fill at this open

    def apply_fills(bar):
        nonlocal cash, qty, trades
        if not pending:
            return
        open_px = price(bar, "o")
        depth = depth_usd(bar, "o_depth")
        for o in pending:
            if o["side"] == "buy":
                notional = int(o["notional_quote_units"]) / QUOTE_UNITS_PER_USDC
                notional = min(notional, cash)
                if notional < 1.0:
                    continue
                fee = notional * FEE_BPS
                net = notional - fee
                fill_px = open_px * (1 + SLIP_BPS) * (1 + net / depth)
                qty += net / fill_px
                cash -= notional
                trades += 1
            else:  # sell
                sell_qty = int(o["qty"]) / 1e8
                sell_qty = min(sell_qty, qty)
                if sell_qty <= 0:
                    continue
                gross = sell_qty * open_px
                fill_px = open_px * (1 - SLIP_BPS) / (1 + gross / depth)
                proceeds = sell_qty * fill_px
                proceeds -= proceeds * FEE_BPS
                cash += proceeds
                qty -= sell_qty
                trades += 1
        pending.clear()

    n = len(bars)
    for k, bar in enumerate(bars):
        apply_fills(bar)
        close_px = price(bar, "c")
        equity = cash + qty * close_px
        if k == 719:
            equity_at_719 = equity
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        positions = []
        if qty > 0:
            positions.append({"symbol": "CBBTC", "qty": str(int(round(qty * 1e8))),
                              "cost_quote_units": "0"})
        account = {"cash_quote_units": str(int(round(cash * QUOTE_UNITS_PER_USDC))),
                   "equity_quote_units": str(int(round(equity * QUOTE_UNITS_PER_USDC))),
                   "positions": positions}
        batch = {"type": "batch", "seq": k, "t": int(bar["t"]),
                 "bars": [dict(bar, symbol="CBBTC")], "fills": [], "account": account}
        proc.stdin.write(json.dumps(batch) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"bot exited early at batch {k}: "
                               + proc.stderr.read()[:500])
        reply = json.loads(line)
        assert reply.get("type") == "reply" and reply.get("seq") == k, reply
        orders = reply.get("orders") or []
        action_log.append(json.dumps(orders, sort_keys=True))
        if k < n - 1:
            pending = orders
        # else: orders on the last bar are rejected by the harness

    # Final flatten at the last close.
    if qty > 0:
        last = bars[-1]
        close_px = price(last, "c")
        depth = depth_usd(last, "c_depth")
        gross = qty * close_px
        fill_px = close_px * (1 - SLIP_BPS) / (1 + gross / depth)
        proceeds = qty * fill_px
        proceeds -= proceeds * FEE_BPS
        cash = proceeds
        qty = 0.0
    proc.stdin.write(json.dumps(
        {"type": "done", "seq": n,
         "account": {"cash_quote_units": str(int(round(cash * QUOTE_UNITS_PER_USDC))),
                     "equity_quote_units": str(int(round(cash * QUOTE_UNITS_PER_USDC))),
                     "positions": []}}) + "\n")
    proc.stdin.flush()
    proc.wait(timeout=30)
    if proc.returncode != 0:
        raise RuntimeError("bot exit code %d: %s" % (proc.returncode,
                                                     proc.stderr.read()[:1000]))
    return cash, trades, max_dd, equity_at_719, action_log


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", default=None)
    ap.add_argument("--bot", default=os.path.join(here, "main.py"))
    args = ap.parse_args()
    candidates = []
    if args.bars:
        candidates.append(args.bars)
    candidates += [
        os.path.join(here, "..", "btc-race-24h-20261118-1444-kit",
                     "dataset", "bars", "CBBTC.ndjson.gz"),
        os.path.join(here, "dataset", "bars", "CBBTC.ndjson.gz"),
    ]
    bars_path = next((p for p in candidates if os.path.exists(p)), None)
    if bars_path is None:
        print("dev bars not found; tried:", candidates, file=sys.stderr)
        return 2
    bars = load_bars(bars_path)
    print(f"bars: {len(bars)}  start ${int(bars[0]['c'])/1e5:,.2f}  "
          f"end ${int(bars[-1]['c'])/1e5:,.2f}  "
          f"buy-and-hold return {int(bars[-1]['c'])/int(bars[0]['c'])-1:+.2%}")
    cash1, trades1, dd1, eq719, log1 = run_bot(args.bot, bars)
    cash2, trades2, dd2, _, log2 = run_bot(args.bot, bars)
    pnl = cash1 - START_USDC
    h1 = (eq719 - START_USDC) if eq719 is not None else 0.0
    h2 = pnl - h1
    print(f"bot dev PnL:      ${pnl:+.2f} ({pnl/10:+.2f}%)  final ${cash1:.2f}")
    print(f"trades:           {trades1}  max drawdown: {dd1:.2%}")
    print(f"first half PnL:   ${h1:+.2f}  (bars 0-719, mark to market)")
    print(f"second half PnL:  ${h2:+.2f}  (bars 720-1439)")
    print(f"dev gate (> $0):  {'PASS' if pnl > 0 else 'FAIL'}")
    print(f"guardrails:       >=1 trade: {'yes' if trades1 >= 1 else 'no'}, "
          f"maxDD <= 25%: {'yes' if dd1 <= 0.25 else 'no'}")
    print(f"determinism:      {'identical action logs (2 runs)' if log1 == log2 else 'MISMATCH'}")
    print(f"second run PnL:   ${cash2 - START_USDC:+.2f}  trades {trades2}")
    return 0 if pnl > 0 and log1 == log2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
