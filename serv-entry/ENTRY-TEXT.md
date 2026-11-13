# SERV Hackathon Ed. 02 — corrected submission text

Derived from Rowan's `serv-submission-prep.md` §1 (entry text) and §3 (X
post draft), with the Q3 count correction applied and the honest limits
updated. Do NOT paste Rowan's originals: they overcount the record — the
two HTTP validation games replay canonical in-process lines, so they are
wins, not independent games. The independent record is
**52–0, aggregate margin +624** (18 held-out +228, 8 + 8 robustness
+90/+102, 18 tuning board +204). Counting the HTTP games as well gives
54 games, +658 — that is the overstated figure, and it must not appear
in the submission.

## Entry text (paste-ready)

**Project name:** Lantern Conquest — Reasoning Agent

**One-liner:** An agent player for the multiplayer strategy game Lantern
Conquest whose every move is chosen by SERV Reasoning — and explained, in
writing, move by move.

**Description:**

Lantern Conquest is a live, playable multiplayer strategy game (flip your
opponents' lanterns on a 7×7 board; corners rule). Our entry adds the
feature the game was missing: an agent player that joins through the same
public API as any human, reads the full board state, and chooses its moves
through SERV Reasoning.

Every turn, the agent enumerates the legal moves and scores each one on
named factors — immediate flips, corner access, mobility, the opponent's
strongest reply, and an exact endgame solve. That candidate set goes to
SERV Reasoning, which returns the chosen move and its rationale. The
rationale is logged in the open: the deciding factors, the opponent reply
being accepted, and why the runner-up move lost. If the service ever
stalls or answers illegally, a local search engine (alpha-beta with the
same named factors) takes the turn instead — the agent never holds a game
hostage to a network call.

The reasoning record is the artifact we are proudest of. Our first
reasoner explained itself beautifully and lost: its safety terms punished
it for approaching corners — the only way into the strongest squares on
the board. The rationale logs made that misdiagnosis visible, we fixed
the values, and the tuned player now beats the game's house bot 52–0
across the in-process test boards, both seats, with per-move
explanations intact (aggregate margin +624; the two HTTP validation
games replay canonical lines and are not counted as independent games).
Stated plainly: the house bot is a 1-ply greedy player, so 52–0 proves a
working reasoning pipeline, not strength against strong human opposition.
We would rather show the reasoning, the failure it exposed, and the fix
than a highlight reel.

Against stronger opposition the picture is honest, not dominant: in a
30-game self-play league against search players of the same family at
different depths and weights, the tuned player went 14–16 (aggregate
margin −6) — 5–5 against the shallower search, 4–6 against the
mobility-weight variant, 5–5 against the deep default. The tuning that
crushes the 1-ply house bot does not dominate other search players, and
the submission says so rather than hiding it behind the 52–0.

The live integration is now measured, not promised. On Nov 13, 2026 the
agent played a full game with SERV Reasoning choosing all 25 of its
moves (zero fallbacks, zero API errors; 24 API calls, $0.22 of credit).
It lost that game 21–28 to the house bot: SERV agreed with the local
search's top move on 19 of 25 turns, and its six divergences cost more
than they gained. A second game the same day proved the fallback end to
end — when the API rejected the client's calls over a deprecated
parameter, the local engine played all 28 moves without stalling and
won 35–14. Both rationale logs ship in the repo's evidence folder. The
SERV layer explains moves beautifully; on this evidence its judgement
over a strong candidate set is the weak link, and the local search
remains the better player. We are submitting the integration with that
finding attached, because a reasoning service you can audit is the
point of the exercise.

**Tech:** Python (stdlib only), the game's public REST API, SERV
Reasoning for move choice and rationale, local alpha-beta fallback with
transposition table and exact endgame solver.

## X post draft (Chris posts at submission)

> Our SERV Hackathon entry is in: a reasoning agent that plays Lantern
> Conquest through its public API and explains every move it makes.
>
> First version explained itself beautifully — and lost. Its own
> rationale logs showed why. Fixed: 52–0 against the house bot since.
>
> Built by my two agents, Ellis + Rowan. Demo + repo below. [links]

(Disclosure is in the text itself — "built by my two agents" — no separate
AI disclaimer needed beyond that honesty.)

## What changed vs Rowan's draft (Nov 8 fix round)

- The old count (54 games, counting the HTTP replays) → 52 independent
  games, aggregate margin +624 (in-process only). The HTTP games
  (35–14, 31–18) are wins, not independent games.
- The rationale pipeline itself was fixed in the same round: solved
  endgames now state the true final score (played out exactly), and the
  runner-up's "main deficit" is now ranked by weighted gaps (corner
  300 / access 25 / mobility 7 / flips 1, final differential 100 per
  stone) instead of raw gaps across mixed units. The 3–4 player
  fallback is disabled — it reused the discredited greedy.
