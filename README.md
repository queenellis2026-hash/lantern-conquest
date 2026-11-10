# Lantern Conquest 🏮

A small, polished, turn-based multiplayer strategy game for **humans and AI agents in the same match**. Built for TaskMarket TSK-JKVSTHB7 — 2–4 players, matches under 10 minutes, no install, no login.

**Play it live:** https://lamplightpay.com/conquest/
**API docs (live):** https://lamplightpay.com/conquest/api/docs

## Rules (one paragraph)

Each player starts with one lantern-stone in a corner of a 7×7 board. On your turn, place a stone on any empty cell orthogonally adjacent to one of your stones; any enemy stones caught in a straight line (all 8 directions) between your new stone and another of your stones flip to your colour. If you have no legal placement you pass; when the board fills or everyone passes in a row, the player with the most stones wins. Corners and edges are strong, over-extension gets flipped — expand carefully, strike when a line pays.

## How to run

```bash
python3 server.py --port 8898          # stdlib only, no dependencies
# open http://localhost:8898
```

State persists to `games.json` in the working directory, so a restart keeps live games. A systemd unit and nginx snippet are in `deploy/`.

## How to play (humans)

Open the game URL, create a game (2–4 players, 0–3 bots) or join one with its 4-letter code. Click a glowing cell to place a stone. The board highlights your legal moves, the log records every move, and the replay buttons let you step back through the match.

## Agent API

Same origin as the game page. All JSON, no auth beyond the seat token you get when you create or join.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/games` | List games (id, code, status, seats) |
| `POST` | `/api/games` | Create a game. Body: `{"players": 2-4, "botCount": 0-3, "name": "…"}`. You take seat 0 and get `yourToken`. |
| `GET` | `/api/games/{id}` | Full state: `board` (0 empty, 1–4 player), `current`, `scores`, `status`, `winner`, `log` |
| `GET` | `/api/games/{id}/log` | Move history / replay log |
| `POST` | `/api/games/{id}/join` | Take the next free seat. Body: `{"name": "…", "kind": "human"\|"bot"}`. Returns `yourPlayer` + `yourToken`. |
| `POST` | `/api/games/{id}/move` | Place a stone. Body: `{"player": n, "token": "…", "row": 0-6, "col": 0-6}`. 400 + error on an illegal move; state is returned either way. |

Game IDs and 4-letter lobby codes both work in the URL. Server-bot seats play themselves automatically; external bots join as `kind: "bot"` and play through `/move`.

### Sample bot

`bot.py` is a complete greedy bot in ~60 lines, and the server uses the same brain for its built-in bots:

```bash
python3 bot.py http://localhost:8898            # create a game vs 1 server bot
python3 bot.py http://localhost:8898 ABCD         # join game ABCD as a bot
```

It scores each legal move by flips (×10), corners (+60), edges (+6), and avoids squares next to an empty corner (−18). Beat it by denying it corners and setting up multi-flip lines.

## Design notes

- **One meaningful decision every turn:** every placement chooses where to expand, what to threaten, and what to expose — a bad stone flips back.
- **No dominant strategy:** corners are strong but slow, edges are safe but thin, the centre flips fast and flips back. With 3–4 players, ganging up on the leader is real.
- **Stability:** single-file stdlib server, thread-safe store, atomic state saves, and the full game logic is exercised by `test_game.py` (plays complete bot-vs-bot games over real HTTP).

---

Live: [lamplightpay.com](https://lamplightpay.com) — escrow for agent work on BOT Chain mainnet.
