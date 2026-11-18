[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Creepzone11/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Creepzone11/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

# btc-race-24h-20261118-1444 — entry, round 4

Looser trend-rider for make.fun competition
`btc-race-24h-20261118-1444` (user handle: `creepzone`,
GitHub: `Creepzone11`). Deadline entries close:
2026-11-18T20:44:00Z = **04:44 WIB 19 Nov 2026**.
Prize total $250 (1st $60, 2nd $40, 3rd $30, 4th $25, 5th $20,
6th–10th $15 each). Only entries with dev PnL > $0 race;
ranking is live-window net PnL alone.

## What changed vs round 3

Round 3 ("Slow trend-rider") made +$12.13 on dev but traded
only twice — both legs of a single rally (buy bar 223, sell
bar 505, dev rank 1653/3156). Its weakness is live: if the
live 24h has no rally with 60-min momentum above +0.40%
exactly at an EMA cross, it trades nothing (PnL $0, fails
the >=1-trade guardrail, no prize). Round 4 changes exactly
one parameter — the momentum threshold, +0.40% → **+0.30%** —
so the bot fires on more of the rallies a live window can
offer. Everything else is identical to round 3.

## What it is

`main.py` (Python 3.13, stdlib only, deterministic, no network,
no model calls, no clock). Speaks `agent-fun/bars-replay/v1`
(NDJSON on stdin/stdout, one reply per batch) directly — no
copied SDK shim.

- **Entry:** EMA(20) crosses above EMA(90) on a bar's close
  AND 60-minute momentum > +0.30%. Full size (100% of equity,
  capped by the harness max-weight). One position at a time.
- **Exit (whole position):** close >= entry x 1.015 (take profit),
  or close <= entry x 0.992 (hard stop), or close <= peak x 0.992
  (trailing stop from the highest close since entry).
- **Guards:** no re-entry for 60 bars after a sell; no new
  entries in the last 60 bars; trading halts if equity falls
  below 98% of the $1,000 start. `max_slippage_bps = 100`.
- **Wire format:** u64 amounts (`notional_quote_units`, `qty`)
  are sent as canonical decimal **strings** — the harness's
  zod schema rejects JSON numbers (this was the round-1/2
  `run_completes` failure). `validate.py` asserts this on
  every reply.

## Validation (local, `python3 validate.py`)

`validate.py` replays the published dev window (1,440 one-minute
CBBTC bars, 2026-11-17 14:45 UTC → 2026-11-18 14:44 UTC) through
the real `main.py` as a subprocess, with the market fill model
(next-minute open, 4 bps fee, 2 bps slippage, constant-product
impact vs open depth), plus a strict wire-format check and a
two-run determinism check:

- **Bot dev PnL: +$4.83 (+0.48%), final $1,004.83 — dev gate PASS**
- Trades: 4 — buy bar 223 / sell bar 505 (+$12.13, the same
  rally trade as round 3) and buy bar 871 / sell bar 1183
  (-$7.30, a chop trade; the stop kept the loss small)
- Max drawdown: 1.02% (guardrail limit 25%)
- First half (bars 0–719): +$12.13; second half (720–1439): -$7.30
- Wire format: PASS (all u64 amounts are canonical strings)
- Determinism: two runs, identical action logs (second run
  also +$4.83, 4 trades)
- Tolerance: EOF without `done`, malformed lines, unknown
  message types, empty stdin — all exit 0, never crash

## Variants measured (same dev window, same fill model)

| Variant | Dev PnL | Trades | Max DD | Verdict |
|---|---|---|---|---|
| round 3 baseline (mom 0.40%, cd 60) | +$12.13 | 2 | 0.80% | gate pass, trades rarely |
| **round 4 (mom 0.30%, cd 60)** | **+$4.83** | **4** | **1.02%** | **chosen: 2x the triggers, still profitable** |
| mom 0.25%, cd 60/30 | +$4.83 | 4 | 1.02% | identical trades to 0.30% on dev |
| mom 0.20%, cd 60/30 | -$9.77 | 6 | 2.46% | FAIL — admits too much chop |
| mom 0.30%, cooldown 30 | +$4.83 | 4 | 1.02% | no change on dev (cooldown never binds) |
| mom 0.30% + re-entry trigger | -$5.00 | 6 | 1.89% | FAIL — re-entries at 549/781 both lose |
| mom 0.30%, take-profit 2.0% | -$0.75 | 4 | 1.69% | FAIL — rally peaks at +1.82%, TP never hits |
| mom 0.30%, stop-loss 0.5% | -$12.94 | 4 | 1.29% | FAIL — tight stop kills the good rally at bar 237 |
| mom 0.30%, lookback 30 min | +$4.83 | 4 | 1.02% | same trades as 60-min lookback |
| mom 0.30%, lookback 120 min | -$6.28 | 2 | 1.02% | FAIL — misses the 223 rally entirely |
| mom 0.25%, lookback 120 min | +$5.28 | 4 | 1.02% | enters the rally late (bar 333); slower to confirm live |

Why the threshold stops at 0.30%: the dev window has exactly
one clean rally (bars ~223–508, +1.8% peak). Every other EMA
cross-up is chop with at most +0.6% of forward room in 300
bars, so any entry there loses about a stop. The 0.30%
threshold admits one such chop trade (-$7.30) and still nets
+$4.83; 0.20% admits two and goes negative. The cliff between
0.25% and 0.20% is the edge of what this window can pay for.

## A validator bug found and fixed

While sweeping, three variants first printed PnL **-$1,000.00**
with max drawdown only ~1–2% — impossible for real trading.
The cause was in the final-flatten step of `validate.py`
(inherited from round 3): it wrote `cash = proceeds`, which
zeroes the account whenever any position — or even float dust
(~1.9e-9 BTC left after a sell) — remains at bar 1439. It
never triggered for round 3 only because that bot was flat at
the end. Fixed here to `cash += proceeds`, and the flatten
now runs only for a real position (worth > $0.01). The
round-3 `validate.py` still carries the latent bug; do not
reuse it for a bot that holds at the end.

## Biggest risk — read this before submitting

**This is a calculated bet, not a guarantee.** Dev profit does
not predict live profit, and this change trades dev PnL for
trigger frequency: +$4.83 instead of +$12.13, for twice as
many setups. The live window is unseen; a lower threshold
also admits more false entries live, each capped at roughly
-$10 by the stop, and the 98% halt caps the damage at about
two stopped-out trades. The bet is that a live window is
more likely to contain a rally the looser filter catches than
a rally the strict filter catches — and that catching one
rally (+1.5% TP ≈ +$15) outweighs one or two false entries.
If the live window is as quiet as the dev window's second
half, both round 3 and round 4 trade little and the extra
triggers buy nothing.

Also: **round 4 replaces round 3 as the final entry** (the
latest submission with a receipt before the deadline is the
one that races). Round 3 stays the entry only if round 4 is
refused at intake. And the per-competition entry cap that
blocked the gta6-01 round 4 an hour earlier may block this
one too — the account already has 3 entries taken in here.

## Files

- `main.py` — the bot
- `validate.py` — local replay validator (see above)
- `README.md` — this file
- `LICENSE` — MIT
- `.makefun/owner.json` — agent wallet (payout wallet)

## Submission note (read before submitting)

This code was written in a Muse app session. A 2026-11-18
correction in the project memory notes that `bundle --dry-run`
in the gta6-twitch-v2 repo **found 4 Muse app sessions** in
`~/agents/`, so a Muse submission *can* be prize-eligible
provided the build is in a clean committed git repo and the
bundle is given `--muse-usage`, `--system-prompt`, `--mcp none`,
`--harness muse-app --provider meta --model muse-spark-1.3
--effort default`. Verify whichever harness records *before*
building/submitting — a handed-over submission is ranked but
takes no paid place. Whoever rebuilds this entry must write
the code in their own recorded session; pasting this file in
verbatim risks the transcript gate (`thinking_reproduces`).
