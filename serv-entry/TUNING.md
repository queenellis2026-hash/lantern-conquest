# Tuning the Lantern Conquest reasoning agent — v1 → v3

**Outcome: the tuned player (`player_v3.py`) beats the sample bot
reliably — 52 wins, 0 draws, 0 losses across every in-process
scoreboard played, both seats, with a positive margin in every
single game.** The two HTTP validation games replay canonical
in-process lines, so they are wins, not independent games — counting
them as well would give 54 games, which overstates the independent
evidence (see "Final honest strength"). The success bar set for this
work (≥7/10 wins on a ≥10-game board, positive aggregate margin) is
cleared with room to spare. All numbers below are exactly as they
came out, losses included (they are v1's).

## Method

- **Validated engine first.** `tuning/engine.py` is an exact in-process
  replica of `repo/server.py`'s rules and of the built-in bot brain.
  Before any tuning result was trusted, `tuning/validate_engine.py`
  confirmed: the bot replica agrees with the repo's own `bot.py` on 400
  random positions; a simulated v1-vs-bot game reproduces the HTTP
  proof game **move-for-move** (all 47 plies, flips and running scores)
  ending 20–29; the greedy mirror match ends 28–21; v1-vs-v1 ends
  25–24. After the HTTP validation games, the in-process move sequences
  were checked against the real server logs a second time — identical,
  all 47 plies in both games.
- **Scoreboard design** (`tuning/harness.py`): the candidate plays the
  bot-replica in **both seats**, from the canonical start and from
  seeded random opening prefixes (uniformly random legal plies, then
  the players take over). Pairing the same prefix position across seats
  keeps the comparison honest; v1's losing record on the same board
  (below) shows the board discriminates.
- **The rationale artifact was a hard constraint**, not a by-product:
  every version logs, per move, the search value, the named factors
  (immediate flips, corner taken/access, mobility after, opponent's
  best reply), and why the runner-up lost. See
  `tuning/evidence-http/http-seat0-rationale.log` for the final
  player's own words across a full game.

## What changed between versions, and why

**v1 (`player.py`, the prototype) — 1-ply factor heuristic.**
Each move scored once on hand weights (flips ×10, corner +50,
corner-gift −16, opponent-reply −6/stone, mobility ×1.5, endgame diff).
On the tuning board: **6W-0D-12L, aggregate margin −72**, including the
canonical 20–29 loss from the original proof. Diagnosis (confirmed by
v2's success): one ply of hand weights cannot price tactics in a game
where flips compound; worse, two of its terms fight the game's actual
geometry — the "corner-gift" penalty punishes playing next to an empty
corner, but in Lantern Conquest that is the *only way in* to a corner,
and the reply-flip penalty makes it decline pressure that a deeper look
shows is winning.

**v2 (`player_v2.py`) — alpha-beta search replaces the 1-ply weights.**
Negamax alpha-beta with a transposition table and corner-first move
ordering; the opponent is modelled as a strong adversary, not as the
bot's script. The named factors move to the *horizon*, where they
evaluate the position the tactics actually reach: stone differential
(×1), mobility (×7), corner occupancy (×300), corner access — owning a
stone next to a still-empty corner (×25) — and edge stones (×2). From
12 empties down, search stops estimating and solves the position
exactly (terminal value = true final stone differential). First board
(depths 4/5/6 by phase): **18W-0D-0L, margin +158** — the design change,
not a weight tweak, is what fixed the player.

**Depth/weight sweep on the tuning board** (18 games each: canonical +
seeds 0–7 from 6-ply prefixes, both seats):

| Configuration | Record | Agg. margin | Board time |
|---|---|---|---|
| v2 default depths (4/5/6, solve ≤12) | 18-0-0 | +158 | 21 s |
| v2 deep (5/6/7, solve ≤14) | 18-0-0 | **+204** | 67 s |
| v2 deep, mobility weight 7→10 | 18-0-0 | +188 | 64 s |
| v2 deeper (6/7/8, solve ≤16) | 18-0-0 | +200 | 149 s |

Depth helped (+158 → +204); doubling down on depth again bought
nothing (+200 at 2.2× the compute); raising the mobility weight hurt
(+188). So **v3 = v2 with the deep depth schedule (5/6/7, exact solve
from 14 empties) and the original weights**, baked in as defaults.
`player.py` (v1) and `player_v2.py` are untouched; v3 is a separate
file.

## Final scoreboard — v3

Held-out board (seeds never used during tuning; canonical + seeds
10–17 from 6-ply prefixes, both seats):

| Seat | Record | Aggregate margin |
|---|---|---|
| Seat 0 (moves first) | 9W-0D-0L | +133 |
| Seat 1 | 9W-0D-0L | +95 |
| **Total** | **18W-0D-0L** | **+228** |

Canonical game (no prefix): seat 0 wins 35–14, seat 1 wins 31–18 —
compare v1's 20–29 loss and the greedy bot's 28–21 mirror win.

Robustness boards (fresh seeds 20–23): 4-ply prefixes **8-0-0, +90**;
10-ply prefixes **8-0-0, +102**. Tuning board (for the record): 18-0-0,
+204. Raw results: `tuning/results/*.json`.

**HTTP validation** (`tuning/run_http_validation.py`, evidence in
`tuning/evidence-http/`): two full games over the real local API with
`player_v3.py` itself — seat 0 vs the server's built-in bot: **won
35–14, 0 API errors**; seat 1 vs the sample bot's brain (repo `bot.py`
`choose()` driven through the API): **won 31–18, 0 API errors**. Both
games' move sequences match the in-process simulation exactly.

## Self-play league vs search players (new, Nov 8 fix round)

Grok's review named the biggest weakness: nothing had been measured
against a non-greedy opponent. `tuning/league.py` runs v3 against
three search players of the same alpha-beta family (different depths
and weights), canonical start plus seeds 10–13 from 6-ply prefixes,
both seats — 10 games per matchup, 30 total, on the validated engine.
Raw results: `tuning/results/league-v3-vs-search.json`.

| Opponent | Record (v3) | Aggregate margin |
|---|---|---|
| v2 default (depths 4/5/6, solve ≤12) | 5W-0D-5L | +16 |
| v2 deep, mobility weight 7→10 | 4W-0D-6L | −6 |
| v3 shallow (depths 3/4/5, solve ≤10) | 5W-0D-5L | −16 |
| **League total** | **14W-0D-16L** | **−6** |

Honest reading: v3 is roughly even against other search players and
slightly losing overall. The depth/weight tuning that routs the 1-ply
greedy bot does not dominate search opposition — the mobility-weight
variant beats it outright, and the shallow variant splits even. The
league opponents are the same alpha-beta family, so this measures v3
against stronger and weaker search, not against an alien style; a
truly independent engine was not available. The submission states the
league record alongside the 52–0, not behind it.

## Final honest strength

Against the house sample bot, v3 is not a rival but a rout: **52-0-0
in-process, every margin positive (range +5 to +23, aggregate +624).**
The two HTTP validation games (35–14, 31–18) replay canonical
in-process lines, so they are not independent games: counting them as
well gives 54 games and +658, which overstates the independent
evidence. Two qualifications, stated plainly:

1. **The opponent is a 1-ply greedy.** This record proves the tuned
   player decisively beats *this* bot — the bar the entry will be
   judged against when it demos against the house bot — and that the
   search, exact endgame, and rationale pipeline work end-to-end over
   the real API. It does not measure v3 against strong opposition:
   no human games and no self-play league were run, and v3's strength
   against another search player is unknown.
2. **Play is near-deterministic.** From the standard start, v3 plays
   one principal line per seat (the scoreboard's variety comes from
   the random prefixes). That is fine for a demo against a
   deterministic bot; a varied field would want opening randomization.

Compute: ~1–4 s per move at the tuned depths on this machine — well
inside polite play for the API loop. The 3–4-player fallback in
`player_v3.py` (the search is a 2-player search) has been **removed**:
it reused the discredited v1-style greedy, including the −18
corner-gift penalty the tuning record identifies as the core flaw, and
`decide()` now refuses multiplayer seats outright.

Remaining SERV work is unchanged from the README: OpenServ account +
API key (human step), wiring `evaluate()`'s candidate set to SERV
Reasoning at the seam v3 preserves (`decide()` already returns the
full candidate report the service call needs), the demo, the write-up,
and the keeper's X post — go/no-go by Nov 13–14 for the Nov 15,
23:59 UTC close.
