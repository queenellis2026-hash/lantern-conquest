#!/usr/bin/env python3
"""Sample bot for Lantern Conquest — the whole agent API in ~60 lines.

Usage:
    python3 bot.py http://localhost:8898            # create a game vs 1 server bot
    python3 bot.py http://localhost:8898 ABCD         # join game ABCD as a bot
    python3 bot.py http://localhost:8898 ABCD MyBot   # ...with a custom name

API used:
    POST /api/games                 -> create a game (you take seat 0)
    POST /api/games/{id}/join       -> take a free seat (kind="bot")
    GET  /api/games/{id}            -> full state: board, current, scores, log
    POST /api/games/{id}/move       -> {"player", "token", "row", "col"}

Board: 0 = empty, 1..4 = player index + 1. A move is legal when the cell is
empty and orthogonally adjacent to one of your stones. Placing flips enemy
stones in a straight line between your new stone and another of yours.
"""
import json
import sys
import time
import urllib.request

SIZE = 7
DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
CORNERS = {(0, 0), (0, SIZE - 1), (SIZE - 1, 0), (SIZE - 1, SIZE - 1)}


def call(base, path, body=None):
    """One API call with retries — public tunnels drop a request now and then;
    a bot that dies on the first hiccup is no use to anyone."""
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(base + path, data=data,
                                         headers={"Content-Type": "application/json"},
                                         method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - retry transient failures
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise last


def legal_moves(board, p):
    me = p + 1
    out = []
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c] != 0:
                continue
            if any(0 <= r + dr < SIZE and 0 <= c + dc < SIZE
                   and board[r + dr][c + dc] == me for dr, dc in ORTHO):
                out.append((r, c))
    return out


def flips_for(board, p, r, c):
    me = p + 1
    out = []
    for dr, dc in DIRS:
        line, nr, nc = [], r + dr, c + dc
        while 0 <= nr < SIZE and 0 <= nc < SIZE:
            v = board[nr][nc]
            if v == 0:
                break
            if v == me:
                out.extend(line)
                break
            line.append((nr, nc))
            nr, nc = nr + dr, nc + dc
    return out


def choose(board, p):
    """Greedy: most flips, corners worth a lot, squares next to an empty
    corner are a trap. Beat this bot by denying it corners and setting up
    multi-flip lines."""
    best, best_score = None, None
    for r, c in legal_moves(board, p):
        s = len(flips_for(board, p, r, c)) * 10
        if (r, c) in CORNERS:
            s += 60
        elif r in (0, SIZE - 1) or c in (0, SIZE - 1):
            s += 6
        for cr, cc in CORNERS:
            if abs(r - cr) + abs(c - cc) == 1 and board[cr][cc] == 0:
                s -= 18
        if best_score is None or s > best_score:
            best, best_score = (r, c), s
    return best


def main():
    base = sys.argv[1].rstrip("/")
    name = sys.argv[3] if len(sys.argv) > 3 else "SampleBot"
    if len(sys.argv) > 2:  # join an existing game by id or code
        g = call(base, f"/api/games/{sys.argv[2]}/join", {"name": name, "kind": "bot"})
    else:  # create a fresh 2-player game against one server bot
        g = call(base, "/api/games", {"players": 2, "botCount": 1, "name": name})
    gid, me, token = g["id"], g["yourPlayer"], g["yourToken"]
    print(f"Joined {gid} (code {g['code']}) as player {me} ({name})", flush=True)
    while True:
        st = call(base, f"/api/games/{gid}")
        if st["status"] == "finished":
            w = st["winner"]
            print("Game over:", "draw" if w == "draw"
                  else f"{st['players'][w]['name']} wins {st['scores']}", flush=True)
            return
        if st["current"] != me:
            time.sleep(1.0)
            continue
        mv = choose(st["board"], me)
        if mv is None:
            print("No legal move — waiting (server passes me).", flush=True)
            time.sleep(1.0)
            continue
        try:
            st = call(base, f"/api/games/{gid}/move",
                      {"player": me, "token": token, "row": mv[0], "col": mv[1]})
        except Exception as e:  # noqa: BLE001 - transport flaked; re-read state
            print(f"Move request failed ({e}) — re-reading state.", flush=True)
            time.sleep(1.0)
            continue
        if "error" in st:
            # e.g. a retried move that already landed: re-read state, carry on
            print(f"Move not applied ({st['error']}) — re-reading state.", flush=True)
            time.sleep(1.0)
            continue
        print(f"Played ({mv[0] + 1},{mv[1] + 1}) — scores {st['scores']}", flush=True)


if __name__ == "__main__":
    main()
