#!/usr/bin/env python3
"""btc-race-24h-20261118-1444 entry, round 4: looser trend-rider, long only, CBBTC/USDC.

Round 3 ("Slow trend-rider") made +$12.13 on the dev window but
only traded twice, both legs of a single rally (buy bar 223,
sell bar 505). Its weakness is live, not on dev: if the live
24h has no rally with 60-min momentum above +0.40% exactly at
an EMA cross, it trades nothing and fails the >=1-trade
guardrail. Round 4 loosens the entry so it fires on more of
the rallies a live window can offer, while keeping every
losing trade small:

  * Entry, trigger A (cross): EMA(20) crosses above EMA(90) on
    a bar's close AND the momentum over MOM_LOOKBACK bars is
    above MOM_THRESHOLD. Full size (100% of equity, capped by
    the harness max-weight). One position at a time.
  * Entry, trigger B (re-entry, only when REENTRY is on): the
    fast EMA is ALREADY above the slow EMA and the momentum
    crosses up through MOM_THRESHOLD (it was at or below the
    threshold on the previous bar). This catches a rally that
    keeps running after the bot sold (take-profit exit) or that
    started before the cross. Still one position at a time and
    still respecting the cooldown after a sell.
  * Exit (whole position): close >= entry * (1 + TAKE_PROFIT),
    or close <= entry * (1 - STOP_LOSS) (hard stop), or
    close <= peak * (1 - STOP_LOSS) (trailing stop from the
    highest close since entry).
  * No re-entry for COOLDOWN_BARS bars after a sell. No new
    entries in the last 60 bars. Trading halts for the window
    if equity falls below HALT_EQUITY_FRACTION of starting
    capital, so a run of false entries cannot grind the
    account down: each stopped-out trade costs roughly
    STOP_LOSS + fees, and the halt caps the total damage.
  * max_slippage_bps = 100 on every order.

Why this shape: on the dev window BTC fell 2.8% and every kit
baseline lost money. One-minute noise is ~6.7 bps per bar
while a full-size round trip costs ~26 bps, so fast signals
just churn fees. The dev window has exactly one clean rally
(bars ~223-508, +1.8% peak); every other EMA cross-up is
chop with at most +0.6% of forward room in 300 bars, so any
entry there loses about a stop. Round 3's 0.40% filter is the
midpoint between the false crosses (momentum <= +0.38%) and
the genuine rally (+0.47%). Round 4 lowers it to 0.30%:
measured on dev it still pays (+$4.83, 4 trades — the same
winning rally trade plus one losing chop trade at -$7.30),
while 0.20% loses (-$9.77) and a re-entry trigger, a 2.0%
take-profit, and a 0.5% stop all lose on dev. The threshold
is lowered only as far as the dev window still pays for it,
and the stop / halt pair keeps each false entry cheap. See
README.md for the measured variants: this file's constants
are the chosen set.

Protocol: agent-fun/bars-replay/v1, newline-delimited JSON on
stdin/stdout, exactly one reply per batch echoing its seq.
Standard library only, deterministic: no randomness, no clock,
no network, no environment reads. All amounts are integers
(quote units, 1 USDC = 1,000,000 units).
"""

import json
import sys

SYMBOL = "CBBTC"

# --- strategy parameters (validated on the dev window, see README.md) ---
FAST_SPAN = 20
SLOW_SPAN = 90
MOM_LOOKBACK = 60
MOM_THRESHOLD = 0.003          # +0.30% over MOM_LOOKBACK minutes
REENTRY = False                # trigger B: momentum spike while already above
TAKE_PROFIT = 0.015            # +1.5% from entry close
STOP_LOSS = 0.008              # -0.8% from entry close / from peak
COOLDOWN_BARS = 60             # no re-entry for 60 bars after a sell
NO_ENTRY_AFTER_SEQ = 1380      # last 60 bars: no new entries
HALT_EQUITY_FRACTION = 0.98    # stop trading if equity < 98% of start
MAX_SLIPPAGE_BPS = 100


class Ema:
    """EMA seeded as the mean of its first `span` closes, then
    value += 2/(span+1) * (close - value).  Float64, deterministic."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return self.value
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span
        return self.value


class Bot:
    def __init__(self, hello):
        self.hello = hello
        capital = hello.get("capital") or {}
        self.start_equity = int(capital.get("quote_units") or 1000000000)
        caps = hello.get("caps") or {}
        self.max_weight_bps = int(caps.get("max_weight_bps") or 10000)
        self.max_orders = int(caps.get("max_orders_per_bar") or 16)
        fees = hello.get("fees") or {}
        self.min_notional = int(fees.get("min_notional_quote_units") or 1000000)
        self.warmup_bars = int(hello.get("warmup_bars") or 0)
        self.seq = -1
        self.closes = []          # float raw closes, oldest first
        self.fast = Ema(FAST_SPAN)
        self.slow = Ema(SLOW_SPAN)
        self.prev_gap = None      # fast - slow on the previous bar
        self.prev_mom = None      # momentum on the previous bar
        self.cash = self.start_equity
        self.equity = self.start_equity
        self.held_qty = 0         # int, from the account (authoritative)
        self.entry_close = None   # close at the bar the buy was decided
        self.peak_close = None
        self.last_sell_seq = -10 ** 9
        self.halted = False
        self.next_client = 1

    def _client_id(self):
        cid = "o%d" % self.next_client
        self.next_client += 1
        return cid

    def _sync_account(self, account):
        if not isinstance(account, dict):
            return
        try:
            self.cash = int(account.get("cash_quote_units", self.cash))
            self.equity = int(account.get("equity_quote_units", self.equity))
        except (TypeError, ValueError):
            pass
        qty = 0
        positions = account.get("positions") or []
        for pos in positions:
            if isinstance(pos, dict) and pos.get("symbol") == SYMBOL:
                try:
                    qty = int(pos.get("qty", 0))
                except (TypeError, ValueError):
                    qty = 0
        self.held_qty = qty
        if qty == 0:
            self.entry_close = None
            self.peak_close = None
        if self.equity < int(self.start_equity * HALT_EQUITY_FRACTION):
            self.halted = True

    def on_batch(self, batch):
        self.seq = int(batch.get("seq", self.seq + 1))
        self._sync_account(batch.get("account"))
        bars = batch.get("bars") or []
        bar = None
        for b in bars:
            if isinstance(b, dict) and b.get("symbol") == SYMBOL:
                bar = b
                break
        if bar is None and len(bars) == 1 and isinstance(bars[0], dict):
            # Defensive: a batch with a single unlabelled bar is ours.
            bar = bars[0]
        if bar is None:
            return []
        try:
            close = float(int(bar["c"]))
        except (TypeError, ValueError, KeyError):
            return []
        if self.seq < self.warmup_bars:
            return []
        self.closes.append(close)
        fast_now = self.fast.push(close)
        slow_now = self.slow.push(close)
        if fast_now is None or slow_now is None:
            self.prev_gap = None
            self.prev_mom = None
            return []
        gap = fast_now - slow_now
        # Momentum over the lookback, only once enough closes exist.
        mom = None
        if len(self.closes) > MOM_LOOKBACK:
            prev_close = self.closes[-1 - MOM_LOOKBACK]
            mom = (close - prev_close) / prev_close
        # Update peak while holding, before deciding.
        if self.held_qty > 0:
            if self.peak_close is None or close > self.peak_close:
                self.peak_close = close
        orders = []
        if self.held_qty > 0 and self.entry_close is not None:
            if (close >= self.entry_close * (1.0 + TAKE_PROFIT)
                    or close <= self.entry_close * (1.0 - STOP_LOSS)
                    or (self.peak_close is not None
                        and close <= self.peak_close * (1.0 - STOP_LOSS))):
                orders.append({
                    "side": "sell",
                    "client_id": self._client_id(),
                    "symbol": SYMBOL,
                    # u64 amounts travel as canonical decimal STRINGS on the
                    # wire (the harness's zod schema rejects JSON numbers).
                    "qty": str(self.held_qty),
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                })
                self.last_sell_seq = self.seq
                self.prev_gap = gap
                self.prev_mom = mom
                return orders[: self.max_orders]
        if self.held_qty == 0 and not self.halted and mom is not None:
            cross_up = (self.prev_gap is not None
                        and self.prev_gap <= 0.0 and gap > 0.0)
            # Trigger B: already above, momentum crossing up through
            # the threshold (it was at or below it last bar).
            spike = (REENTRY and self.prev_gap is not None
                     and self.prev_gap > 0.0 and gap > 0.0
                     and self.prev_mom is not None
                     and self.prev_mom <= MOM_THRESHOLD
                     and mom > MOM_THRESHOLD)
            if (self.seq < NO_ENTRY_AFTER_SEQ
                    and self.seq - self.last_sell_seq >= COOLDOWN_BARS
                    and (cross_up or spike)
                    and mom > MOM_THRESHOLD):
                room = self.equity * self.max_weight_bps // 10000
                notional = self.cash if self.cash < room else room
                if notional >= self.min_notional and notional > 0:
                    orders.append({
                        "side": "buy",
                        "client_id": self._client_id(),
                        "symbol": SYMBOL,
                        # u64 amounts travel as canonical decimal STRINGS
                        # on the wire (the harness's zod schema rejects
                        # JSON numbers) — this was the run_completes bug.
                        "notional_quote_units": str(int(notional)),
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    })
                    # Remember the entry close now; the account in
                    # the next batch confirms whether it filled.
                    self.entry_close = close
                    self.peak_close = close
        self.prev_gap = gap
        self.prev_mom = mom
        return orders[: self.max_orders]


def main():
    bot = None
    out = sys.stdout
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            # A malformed line must not kill the run: skip it.
            continue
        if not isinstance(msg, dict):
            continue
        kind = msg.get("type")
        if kind == "hello":
            bot = Bot(msg)
        elif kind == "batch":
            if bot is None:
                # A batch before hello: start with defaults so we can
                # still answer it instead of exiting.
                bot = Bot({})
            orders = bot.on_batch(msg)
            reply = {"type": "reply", "seq": int(msg.get("seq", 0)),
                     "orders": orders}
            out.write(json.dumps(reply, separators=(",", ":")) + "\n")
            out.flush()
        elif kind == "done":
            if bot is not None:
                bot._sync_account(msg.get("account"))
            return 0
        else:
            # Unknown message type: ignore it, never exit non-zero.
            continue
    # stdin closed without "done": the run still completed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
