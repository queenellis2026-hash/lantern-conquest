# Lantern Conquest — Reasoning Agent (SERV Hackathon Ed. 02 entry)

The SERV Hackathon Ed. 02 (OpenServ) feature for Lantern Conquest: **a
reasoning agent that plays the game through its public API, explaining
every move it makes.** The prototype below was built Nov 8, 2026; the
SERV Reasoning integration it was designed for is the entry's new
feature, wired through `serv_reason.py`.

## What's here

| File | What it is |
|---|---|
| `player.py` | The reasoning agent, v1 (Python, stdlib only — matches the game's tooling). Kept as the honest record of the first reasoner. |
| `player_v3.py` | **v3, the tuned final player** — alpha-beta search with the named factors at the horizon, an exact endgame solver, and the tuned depth schedule baked in. |
| `serv_reason.py` | The SERV Reasoning client: sends each turn's candidate set (board, legal moves, factor breakdown) to the SERV Reasoning API, validates the returned move against the legal list, and falls back to the local best on any failure. Reads its API key from the `SERV_API_KEY` environment variable — never from the repo. |
| `TUNING.md` | The full tuning record: method, version scoreboards, final honest strength. |
| `tuning/` | The validated in-process engine, scoreboard harness, HTTP validation driver, and all raw results/evidence. |
| `game-server/` | The Lantern Conquest game server and its sample bot, carrying the restart token fix (see the wart note at the end). |
| `evidence/` | Game logs, final states, rationale logs, and the greedy baseline (details below). |

## How the prototype works

`player.py` plays exactly the way a third-party agent is supposed to:

1. **Enters through the public API** — `POST /api/games` (create) or
   `POST /api/games/{id}/join`, takes a seat, and keeps the seat token it
   is issued. No other auth exists or is used.
2. **Reads the full board state** (`GET /api/games/{id}`) before every
   decision, and only ever moves when the server says it is its turn.
3. **Reasons explicitly before each move.** It enumerates every legal
   move, simulates each one on a board copy, and scores it on named,
   weighted factors:
   - immediate flips (stones gained now),
   - positional value (corner ≫ edge),
   - corner-gift danger (playing next to a still-empty corner),
   - **a 1-ply lookahead**: the strongest reply any opponent then has —
     how many stones it flips, and whether it hands them a corner,
   - post-move mobility (my legal moves vs the best opponent's),
   - in the endgame (≤8 empties), raw stone differential.
4. **Writes a rationale for every chosen move** — the deciding factors in
   plain words, the opponent's best reply it is accepting, and why the
   runner-up lost (or that the tie was broken deterministically). One log
   line per move; see `evidence/gameA-rationale.log`.
5. **Plays politely**: polls at 0.7s, retries transient transport errors,
   treats a rejected move as "re-read state", never spams.

One API subtlety that matters: the agent takes its seat as kind `human`,
on purpose. The server's `bot_worker` auto-plays **any** seat marked
`bot` — including externally joined ones — so a `bot`-kind seat would be
played *by the server* half the time and the reasoning would be theatre.
Kind only selects who drives the seat; the seat is the token holder's
either way.

## Evidence — the test games (all local, server on 127.0.0.1)

Produced by the prototype's proof driver against the game server running
locally on port 8899; the scoreboard harness that validates the tuned
player lives in `tuning/`.

| Game | Matchup | Result | Moves | API errors |
|---|---|---|---|---|
| A — `g-3884egvt` (code OBEM) | Reasoner (seat 0) vs server built-in bot (seat 1; `bot.py`'s brain) | **Bot wins 29–20** | 47 total, 24 by the reasoner | 0 |
| B — `g-albvasfc` (code RBMI) | Reasoner-A (seat 0) vs Reasoner-B (seat 1, joined by code) | **Reasoner-A wins 25–24** | 47 total (24 + 23) | 0 |
| Baseline — `g-l6qhocbs` (code RDQL) | Sample `bot.py` itself (seat 0) vs server built-in bot | **Sample bot wins 28–21** | 47 | — |

### Live SERV games (Nov 13, 2026)

Two full games played through the wire against the server's built-in
bot, with `player_v3.py --serv` driving seat 0:

| Game | Driving | Result | SERV calls | Cost |
|---|---|---|---|---|
| `g-zpqd8rdk` (TKWE) | SERV Reasoning chose all 25 moves (0 fallbacks, 0 API errors) | **Bot wins 28–21** | 24 | $0.22 |
| `g-d818l9mg` (WQIZ) | Local fallback played all 28 moves (SERV rejected the deprecated `temperature` parameter) | **Reasoner wins 35–14** | 0 answered | $0.00 |

Logs: `evidence/serv-live-game-rationale.log`,
`evidence/serv-fallback-game-rationale.log`.

The honest finding from the live game: SERV agreed with the local
search's top move on 19 of 25 turns, and its six divergences cost more
than they gained — the same local engine that goes 52–0 against this
bot lost 21–28 when SERV held the pen. SERV's rationales are fluent and
factor-grounded, but its judgement over the candidate set is weaker
than the search it was choosing from. The fallback game is the other
half of the design working as intended: when the API rejected every
call, the agent never stalled, played the whole game locally, and won.

Files: `evidence/gameA-{final-state,server-log}.json`,
`evidence/gameA-rationale.log`, `evidence/gameB-…` (both agents'
rationales), `evidence/baseline-greedy-seat0.json`,
`evidence/rematch-rationale.log` (three repeats of Game A),
`evidence/rematch-v2-rationale.log` (one retuned-weights repeat).

### The honest finding: the reasoner currently loses to the sample bot

Both sides are deterministic, so Game A repeated three times produces the
identical 20–29 line, and a retuned variant (flip weight 12, reply penalty
−3) chose the identical moves and lost identically. Meanwhile the plain
greedy sample bot, given the same seat 0, **wins** its mirror match 28–21.
So this is not seat disadvantage: as weighted, the prototype's safety and
mobility terms steer it off the greedy line in the mid-game and it gives
back more than the caution saves. On a 7×7 board where flips compound,
one ply of "don't get flipped back" is worth less than immediate pressure.

What this means for the entry: **the prototype proves the plumbing** —
API play, full-state reading, an inspectable reasoning step, a written
rationale per move, zero errors across 94 agent moves in two full games —
and the rationale logs are exactly the artifact a "reasoning agent" entry
needs to show. **It does not yet prove a strong player.** Beating (or
credibly rivalling) the house bot is tuning work, listed first below.

*Addendum (same day): that tuning work is done — see `TUNING.md`. The
search-based successor, `player_v3.py`, beats the house bot 52-0-0
across the in-process scoreboards (aggregate +624); the two HTTP
validation games replay canonical lines and are not independent
games. The finding above stands as the accurate record of v1, the
1-ply prototype.*

## Mapping to the real SERV entry

The hackathon (from the team's sweep research): SERV Hackathon Ed. 02,
OpenServ; closes **Nov 15, 2026, 23:59 UTC**; $5,000 pool; agent-native —
entries must use **SERV Reasoning**; existing projects are allowed
**with a new feature**; entry needs an OpenServ account/API key, a
public repo, a demo, a write-up, and an X post by the deadline. (No
public payout history for Ed. 01 — medium confidence in the prize, per
the sweep. Measured at signup, Nov 13, 2026: the account's credit grant
was $1.00. A full live game through SERV Reasoning (25 agent moves)
measured $0.22 of that grant — see the live games under Evidence.)

The new feature for the existing Lantern Conquest project = this agent:
*Lantern Conquest gains an agent player whose moves are chosen by SERV
Reasoning.* The seam is already cut for it:

- **Where SERV plugs in:** `evaluate()` in `player.py` produces, per turn,
  a candidate list with factor scores. In the real entry, that candidate
  set (board state, legal moves, factor breakdown) is sent to the SERV
  Reasoning API; the service's chosen move + its generated rationale come
  back and are logged in the same format the local reasoner already
  writes. The local heuristic stays as the offline fallback (and as the
  demo path if credits run out).
- **What wiring that takes (engineering, est. hours, not days):**
  1. An OpenServ account and API key, supplied to the client as the
     `SERV_API_KEY` env var — never in the repo. **Done Nov 13, 2026:**
     the account is live and the key is held in secure storage.
  2. A thin `serv_reason.py` client: POST the turn context, parse the
     returned move, validate it against the legal-move list (fall back to
     the local best on any parse/timeout/illegal answer — the agent must
     never stall a game waiting on the service).
  3. Prompt/context design: give the service the same factors the local
     reasoner computes, so its rationale stays grounded in the position
     instead of free-associating.
  4. Credit budgeting: a full game is ~25 agent moves. Measured live on
     Nov 13, 2026: 24 SERV calls, 52,430 prompt + 7,802 completion
     tokens, $0.22 against the $1.00 signup grant — roughly four full
     games per grant dollar at the default model
     (claude-sonnet-5.5). The local fallback covers any gap.
- **What humans must do (Ellis/Chris):**
  - Create the OpenServ account and API key — done Nov 13, 2026.
  - Post the required **X post** at submission (keeper's account — the
    standing rule is demos/submissions ride the keeper's channels).
  - Make the final go/no-go call, ideally by **Nov 13–14**, so the
    integration and demo aren't a deadline-night build.
- **Deliverables to assemble:** public repo (this prototype merged into
  the lantern-conquest repo or a linked repo), a recorded demo (a full
  reasoner-vs-bot game with the rationale log scrolling is the natural
  demo), and the write-up (the "How it works" and "honest finding"
  sections above are a head start — the entry is *stronger* for showing
  the reasoning losing and being tuned than for hiding it).

## Honest remaining work before Nov 15, 23:59 UTC

1. **Tune the player. — DONE (Nov 8, 2026; see TUNING.md).** The tuned
   player is `player_v3.py`: alpha-beta search with the named factors
   evaluated at the horizon, an exact endgame solver, and the same
   per-move rationale discipline. Final record against the sample bot:
   **52W-0D-0L across the in-process boards** (18-0-0 on the held-out
   scoreboard, aggregate margin +228; canonical game won 35–14 / 31–18
   by seat; the two HTTP validation games replay those canonical lines
   and are not independent games). The entry no longer demos an
   articulate loser. (Caveat, stated in TUNING.md: the record is
   against a 1-ply greedy; strength against strong opposition is
   unmeasured.)
2. **SERV integration — DONE (Nov 13, 2026).** Account, client, prompt,
   fallback and credit test are all live-verified; see the two live
   games under Evidence. Two API behaviours cost real debugging and are
   recorded for anyone repeating this: the SERV layer rejects
   `response_format: {"type": "json_object"}` (it wants `json_schema`;
   omitting the field works), and it rejects a `temperature` parameter
   for this model as deprecated. Both times the local fallback took the
   turn without stalling the game — the second rejection actually
   played a complete game that way (Evidence, fallback game).
3. **Demo + write-up + repo polish**, then the keeper's X post and the
   submission itself.
4. Known wart from the upstream repo, fixed in this one: the original
   server's `games.json` token keys stringify on save, so a *restarted*
   server rejects previously issued tokens. The server under
   `game-server/` is the patched build — the same code that runs the
   live game — so the entry repo carries the fix.

## Run it yourself

```bash
python3 game-server/server.py --port 8899 &    # the game, locally
python3 player.py --base http://127.0.0.1:8899 --create --bots 1 \
    --name Reasoner --rationale-log my-game.log
```
