# MANIFEST — SERV Hackathon Ed. 02 entry repo (STAGING)

Assembled: Fri Nov 13, 2026 (America/Chicago)
Staging dir: `~/workspace/500-goal/serv-entry-repo/`
Status: **staging only — nothing pushed to GitHub, nothing submitted.**

## Included files and their sources

### Entry core — from `~/workspace/500-goal/serv-review/src/serv-agent/`
| Staged file | Source |
|---|---|
| `README.md` | `src/serv-agent/README.md` — judged entry-appropriate as-is (how it works, how to run, the honest v1-lost finding, the final 52–0 record), so copied under its own name, NOT as README-prototype.md. See "Questionable" for its stale references. |
| `ENTRY-TEXT.md` | `~/workspace/500-goal/serv-review/corrected-submission-text.md` — source of truth for entry text; carries the corrected **52** independent-games figure (verified in the staged copy). |
| `player.py` | `src/serv-agent/player.py` (v1 reasoning agent) |
| `player_v3.py` | `src/serv-agent/player_v3.py` (tuned final player) |
| `TUNING.md` | `src/serv-agent/TUNING.md` |
| `tuning/` (7 code files) | `src/serv-agent/tuning/` — engine.py, harness.py, league.py, run_http_validation.py, test_fix_round.py, validate_engine.py, plus `results/` (10 JSON scoreboards) and `evidence-http/` (6 HTTP validation files). `__pycache__` pruned. |
| `evidence/` (10 files) | `src/serv-agent/evidence/` — gameA/gameB final states, server logs, rationale logs, rematch logs, greedy baseline. |

### Game server — `game-server/`
| Staged file | Source |
|---|---|
| `game-server/server.py` | **Pulled live from Hetzner** `/home/ellis/lantern-conquest/server.py` — carries the H2 restart fix. **md5 `92bd31ae53560d19d97252a86a46cc29` — verified exact match** with the expected hash. NOTE: not taken from the GitHub repo (the repo does not carry the H2 fix yet). |
| `game-server/bot.py`, `game-server/test_game.py`, `game-server/static/{app.js,index.html,style.css}` | Mirrored from the local working copy of the lantern-conquest repo at `~/workspace/experiment/wallet/strategy-game/` (no `.git` dir there; its `server.py` hashes identical to the live Hetzner file). |
| `game-server/README-game.md` | The repo working copy's `README.md`, renamed to avoid colliding with the entry README. |
| `game-server/deploy/{lantern-conquest.service,nginx-conquest.conf}` | Same working copy — deployment configs, included for completeness; contain no secrets. |

## Deliberately EXCLUDED
- `games.json` (from the repo working copy) — live game state for 34 stored games; contains live per-seat tokens for the running server. State, not source. Excluding it means the staged server starts fresh.
- `player_v2.py`, `run_proof.py` (exist in `src/serv-agent/`, not on the copy list) — v2 is superseded by v3; run_proof.py regenerates `evidence/` against a local server.
- `__pycache__/` dirs — pruned from the staged tree.
- TaskMarket submission text (`submit/submission.txt` in the working copy) — belongs to the earlier TaskMarket submission (TSK-JKVSTHB7), not to the SERV entry; staged as `game-server/submission-taskmarket.txt` for provenance only. **Do not ship it as entry material without a decision.**

## MISSING — known, not invented
1. **`serv_reason.py` — MISSING.** The SERV Reasoning API client does not exist yet (Rowan is writing it). Nothing fabricated in its place. The entry cannot be submitted until this exists and the $5-credit test has run.
2. **Demo recording — MISSING.** No demo video/screen recording exists in the tree.

## Secret sweep — result: NO credentials
Grepped the whole staged tree for `serv_…` key patterns, `sk-…`, AWS key shapes, `PRIVATE KEY` blocks, and api-key/password/secret assignments: **zero hits.** All other "token" matches are code references to the game's own per-seat tokens, which the server generates at runtime — not credentials.
One artifact to know about: `evidence/baseline-greedy-seat0.json` embeds one seat token (`9on2…`, value not reproduced here) from a finished local proof game on 127.0.0.1. It grants access to nothing that still exists. Flagged for awareness; harmless to ship, trivial to scrub if preferred.

## Questionable / needs a decision before submission
- **README staleness:** the staged `README.md` describes a `repo/` subdir (unmodified GitHub clone) and references `player_v2.py` and `run_proof.py` — none of which are in this tree (the server lives under `game-server/` instead, and v2/run_proof were excluded by the copy list). Its "Run it yourself" paths also point at `repo/server.py`. The README's substance is entry-appropriate, but its file map needs a pass to match this tree before it ships.
- **README claim check:** README says the GitHub repo "does not carry the [H2] fix yet" — consistent with what we found: the fix is in the staged `game-server/server.py` (from the live server), which is exactly why staging pulled from Hetzner.
- **game-server extras:** `deploy/` configs and the TaskMarket submission text came along with the repo mirror; they're authentic repo contents but not SERV-entry material per se. Keep-or-drop is a packaging call.
- **Evidence token:** see Secret sweep — one dead local-game seat token inside a JSON evidence file.

## Post-assembly pass (Ellis, Nov 13, 2026)
- README.md path pass DONE: file map matches the staged tree (serv_reason.py
  and game-server/ rows in; player_v2.py, run_proof.py, repo/ rows out);
  credit figures corrected to the measured ones ($1.00 grant, test calls
  under a cent); account/API-key status updated to done (Nov 13); the
  games.json token wart now described as fixed in game-server/server.py.
- evidence/baseline-greedy-seat0.json: the seat tokens from the finished
  local proof game are REDACTED in place. Tree re-swept: no live tokens ship.
- Still missing at ship time: serv_reason.py (Rowan), the demo recording,
  and the README's final status lines (demo link) once the demo exists.
