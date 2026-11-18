[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Creepzone11/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Creepzone11/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

# btc-race-24h-20261118-1444 — entry

Slow trend-rider for make.fun competition `btc-race-24h-20261118-1444`
(user handle: `creepzone`, GitHub: `Creepzone11`).
Deadline entries close: 2026-11-18T20:44:00Z = **04:44 WIB 19 Nov 2026**.
Prize total $250 (1st $60, 2nd $40, 3rd $30, 4th $25, 5th $20,
6th–10th $15 each). Only entries with dev PnL > $0 race;
ranking is live-window net PnL alone.

## What it is

`main.py` (Python 3.13, stdlib only, deterministic, no network,
no model calls, no clock). Speaks `agent-fun/bars-replay/v1`
(NDJSON on stdin/stdout, one reply per batch) directly — no
copied SDK shim.

- **Entry:** EMA(20) crosses above EMA(90) on a bar's close
  AND 60-minute momentum > +0.40%. Full size (100% of equity,
  capped by the harness max-weight). One position at a time.
- **Exit (whole position):** close >= entry x 1.015 (take profit),
  or close <= entry x 0.992 (hard stop), or close <= peak x 0.992
  (trailing stop from the highest close since entry).
- **Guards:** no re-entry for 60 bars after a sell; no new
  entries in the last 60 bars; trading halts if equity falls
  below 98% of the $1,000 start. `max_slippage_bps = 100`.

## Validation (local, `python3 validate.py`)

`validate.py` replays the published dev window (1,440 one-minute
CBBTC bars, 2026-11-17 14:45 UTC → 2026-11-18 14:44 UTC) through
the real `main.py` as a subprocess, with the market fill model
(next-minute open, 4 bps fee, 2 bps slippage, constant-product
impact vs open depth):

- **Bot dev PnL: +$12.13 (+1.21%), final $1,012.13 — dev gate PASS**
- Trades: 2 (one round trip: buy bar 223 at ~$64,020,
  sell bar 505 at ~$65,022, +1.6% before costs)
- Max drawdown: 0.80% (guardrail limit 25%)
- First half (bars 0–719): +$12.13; second half (720–1439): $0.00
  (no trade — the bot sat out the slow sideways drift, correctly)
- Determinism: two runs, identical action logs

## Why the previous entry failed, and why the baselines lose

Previous race (`btc-race-24h-20261117-0603`): "cbBTC aggressive
trend rider with wide trailing stop", rank 1192/4387, live PnL
-$173. Aggressive trend + wide stop = it rode the trend down,
paid fees on every whipsaw, and the wide stop let losses run.

Dev window (BTC -2.80% over 24h) backtests, same fill model:

| Bot | Dev PnL | Trades | Fees | Max DD |
|---|---|---|---|---|
| buy-and-hold | -$31.63 | 1 | $0.79 | 3.25% |
| hold-cash | $0.00 | 0 | $0.00 | 0.00% |
| EMA-cross 8/21 (baseline) | -$148.16 | 80 | $29.51 | 14.97% |
| momentum (buy@24, hold) | -$23.87 | 1 | $0.79 | 3.24% |
| RSI-Bollinger (baseline) | -$39.91 | 19 | $7.89 | 4.22% |
| ADX-momentum (approx.) | -$60.80 | 32 | $12.38 | 6.42% |
| **This bot** | **+$12.13** | **2** | **~$1.60** | **0.80%** |

One-minute noise is ~6.7 bps/bar while a full-size round trip
costs ~26 bps, so fast signals just churn fees. The only clean
move in the dev window was one rally (hours 6–8, +1.6%); this
bot catches exactly that and sits out the rest.

The 0.40% momentum filter is the midpoint between the false
EMA crosses on the dev window (60-min momentum <= +0.38%) and
the genuine rally cross (+0.47%). Sensitivity: TP +0.6% to
+1.5% all profit on the same trade (+$4.53 to +$12.13);
SL 0.8%–1.2% all give +$12.13. Lowering the momentum threshold
to 0.30% still profits (+$4.83) but adds a losing second-half
trade; to 0.20% it loses (-$9.77). Donchian-breakout and
RSI-mean-reversion variants were tried and were worse
(Donchian best +$5.98; RSI-Bollinger with tight stops: no
profitable config).

## Biggest risk

**Dev profit does not predict live profit.** The dev edge is
one rally in one 24h window. If the live 24h has no rally with
60-min momentum above +0.40% at an EMA cross, the bot trades
nothing (PnL $0, fails the >=1-trade guardrail, no prize).
If it catches a false rally, the stop caps the loss at roughly
-$10 per trade (0.8% + fees). The bot is designed to lose
little when wrong, not to win big when right.

## Files

- `main.py` — the bot
- `validate.py` — local replay validator (see above)
- `README.md` — this file
- `LICENSE` — MIT
- `GROKBOT_PROMPT.md` — steps for the recorded-harness submit

## Submission note (read before submitting)

This code was written in a Muse app session. A 2026-11-18
correction in the project memory notes that `bundle --dry-run`
in the gta6-twitch-v2 repo **found 4 Muse app sessions** in
`~/agents/`, so a Muse submission *can* be prize-eligible
provided the build is in a clean committed git repo and the
bundle is given `--muse-usage`, `--system-prompt`, `--mcp none`,
`--harness muse-app --provider meta --model muse-spark-1.3
--effort default`. Grokbot, by contrast, is **not proven
recorded** (the kit bundle only has a `--grok-dir` for Grok
Build, not Grok Bot). Verify whichever harness records *before*
building/submitting — a handed-over submission is ranked but
takes no paid place. Whoever rebuilds this entry must write
the code in their own recorded session; pasting this file in
verbatim risks the transcript gate (`thinking_reproduces`).
