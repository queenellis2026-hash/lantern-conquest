#!/usr/bin/env python3
"""Lantern Conquest — a small turn-based multiplayer strategy game.

Turn-based, 2-4 players, on a 7x7 board. Humans play in a browser at a
public URL; agents play via a simple HTTP/JSON API (see README.md / /api/docs).

Rules (one paragraph): each player starts with one lantern-stone in a corner.
On your turn, place a stone on any empty cell orthogonally adjacent to one of
your stones; any enemy stones caught in a straight line (all 8 directions)
between your new stone and another of your stones flip to your colour. If you
have no legal placement you pass; when the board fills or everyone passes in
a row, the player with the most stones wins. Corners and edges are strong,
over-extension gets flipped.

Stdlib only. Run: python3 server.py [--port 8898] [--host 127.0.0.1]
State persists to games.json in the working directory.
"""
import json
import os
import random
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SIZE = 7
COLORS = ["#f59e0b", "#2dd4bf", "#fb7185", "#a78bfa"]
NAMES = ["Amber", "Teal", "Rose", "Violet"]
DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
CORNERS = {(0, 0), (0, SIZE - 1), (SIZE - 1, 0), (SIZE - 1, SIZE - 1)}
STARTS = [(0, 0), (SIZE - 1, SIZE - 1), (0, SIZE - 1), (SIZE - 1, 0)]

LOCK = threading.RLock()
STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games.json")


# ---------------------------------------------------------------- game logic
def empty_board():
    return [[0] * SIZE for _ in range(SIZE)]


def legal_moves(board, p):
    """Empty cells orthogonally adjacent to one of p's stones."""
    me = p + 1
    moves = []
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c] != 0:
                continue
            for dr, dc in ORTHO:
                nr, nc = r + dr, c + dc
                if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == me:
                    moves.append([r, c])
                    break
    return moves


def flips_for(board, p, r, c):
    """Enemy stones flipped by placing p's stone at (r, c). Othello lines."""
    me = p + 1
    out = []
    for dr, dc in DIRS:
        line = []
        nr, nc = r + dr, c + dc
        while 0 <= nr < SIZE and 0 <= nc < SIZE:
            v = board[nr][nc]
            if v == 0:
                break
            if v == me:
                out.extend(line)
                break
            line.append([nr, nc])
            nr, nc = nr + dr, nc + dc
    return out


def scores(board, n):
    s = [0] * n
    for row in board:
        for v in row:
            if v:
                s[v - 1] += 1
    return s


def all_seated(game):
    """A seat counts as seated when it is a bot or a human who joined."""
    return all(p.get("seated") for p in game["players"])


def new_game(num_players, bot_seats, creator_name="Player 1"):
    gid = "g-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    code = "".join(random.choices(string.ascii_uppercase, k=4))
    board = empty_board()
    players = []
    for i in range(num_players):
        r, c = STARTS[i]
        board[r][c] = i + 1
        players.append({
            "index": i,
            "name": creator_name if i == 0 else (f"Bot {i + 1}" if i in bot_seats else f"Player {i + 1}"),
            "color": COLORS[i],
            "kind": "bot" if i in bot_seats else "human",
            "eliminated": False,
            "seated": i == 0 or i in bot_seats,
        })
    game = {
        "id": gid,
        "code": code,
        "name": "Lantern Conquest",
        "size": SIZE,
        "status": "playing" if all_seated({"players": players}) else "lobby",
        "players": players,
        "board": board,
        "current": 0,
        "turn": 1,
        "winner": None,
        "scores": scores(board, num_players),
        "log": [],
        "createdAt": int(time.time()),
        "tokens": {},
    }
    return game


def advance(game):
    """Move `current` to the next player who can move; finish if none can."""
    n = len(game["players"])
    board = game["board"]
    # anyone left standing?
    alive = [i for i in range(n) if game["scores"][i] > 0]
    if len(alive) == 1:
        game["status"] = "finished"
        game["winner"] = alive[0]
        return
    if all(board[r][c] != 0 for r in range(SIZE) for c in range(SIZE)):
        finish_by_score(game)
        return
    for step in range(1, n + 1):
        nxt = (game["current"] + step) % n
        if game["scores"][nxt] > 0 and legal_moves(board, nxt):
            game["current"] = nxt
            return
    finish_by_score(game)


def finish_by_score(game):
    game["status"] = "finished"
    top = max(game["scores"])
    winners = [i for i, s in enumerate(game["scores"]) if s == top]
    game["winner"] = winners[0] if len(winners) == 1 else "draw"


def apply_move(game, p, r, c):
    """Apply a legal move. Returns (ok, error, flipped)."""
    if game["status"] != "playing":
        return False, "game is not in play", []
    if p != game["current"]:
        return False, "not your turn", []
    if not (0 <= r < SIZE and 0 <= c < SIZE):
        return False, "cell out of board", []
    if game["board"][r][c] != 0:
        return False, "cell occupied", []
    if [r, c] not in legal_moves(game["board"], p):
        return False, "cell must be orthogonally adjacent to one of your stones", []
    flipped = flips_for(game["board"], p, r, c)
    game["board"][r][c] = p + 1
    for fr, fc in flipped:
        game["board"][fr][fc] = p + 1
    game["scores"] = scores(game["board"], len(game["players"]))
    game["log"].append({
        "turn": game["turn"],
        "player": p,
        "row": r,
        "col": c,
        "flipped": flipped,
        "scores": list(game["scores"]),
    })
    game["turn"] += 1
    game["lastMove"] = {"row": r, "col": c, "player": p}
    # elimination check: anyone at zero stones is out
    for i, s in enumerate(game["scores"]):
        if s == 0:
            game["players"][i]["eliminated"] = True
    advance(game)
    return True, None, flipped


# ---------------------------------------------------------------- bot brain
def bot_choose(game, p):
    """Greedy bot: most flips, with positional weights (corners good, cells
    next to empty corners bad, edges mildly good)."""
    board = game["board"]
    best, best_score = None, None
    for r, c in legal_moves(board, p):
        flipped = flips_for(board, p, r, c)
        s = len(flipped) * 10
        if (r, c) in CORNERS:
            s += 60
        elif r in (0, SIZE - 1) or c in (0, SIZE - 1):
            s += 6
        for cr, cc in CORNERS:
            if abs(r - cr) + abs(c - cc) == 1 and board[cr][cc] == 0:
                s -= 18
        if best_score is None or s > best_score:
            best, best_score = [r, c], s
    return best


# ---------------------------------------------------------------- store
GAMES = {}


def save_store():
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(GAMES, f)
    os.replace(tmp, STORE_PATH)


def load_store():
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH) as f:
                GAMES.update(json.load(f))
        except Exception:
            pass


def public_state(game):
    g = {k: v for k, v in game.items() if k != "tokens"}
    return g


# ---------------------------------------------------------------- bot worker
def bot_worker():
    """After any move, play out server-bot turns with a short pause."""
    while True:
        time.sleep(0.6)
        with LOCK:
            for game in list(GAMES.values()):
                if game["status"] != "playing":
                    continue
                cur = game["players"][game["current"]]
                if cur["kind"] != "bot":
                    continue
                mv = bot_choose(game, game["current"])
                if mv is None:
                    # bot has no move: force a pass by advancing
                    advance(game)
                    save_store()
                    continue
                apply_move(game, game["current"], mv[0], mv[1])
                save_store()


# ---------------------------------------------------------------- HTTP layer
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # -- helpers
    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def _game(self, gid):
        with LOCK:
            g = GAMES.get(gid)
            if g is None:
                # also allow lookup by 4-letter code
                for game in GAMES.values():
                    if game["code"].upper() == gid.upper():
                        return game
            return g

    # -- routes
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/docs":
            return self._send(200, API_DOCS)
        if path == "/api/games":
            with LOCK:
                lst = [{"id": g["id"], "code": g["code"], "status": g["status"],
                        "players": len(g["players"]),
                        "seated": sum(1 for p in g["players"] if p.get("seated")),
                        "createdAt": g["createdAt"]} for g in GAMES.values()]
            return self._send(200, {"games": lst})
        if path.startswith("/api/games/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3]:
                g = self._game(parts[3])
                if g is None:
                    return self._send(404, {"error": "game not found"})
                return self._send(200, public_state(g))
            if len(parts) == 5 and parts[4] == "log":
                g = self._game(parts[3])
                if g is None:
                    return self._send(404, {"error": "game not found"})
                return self._send(200, {"id": g["id"], "code": g["code"], "log": g["log"]})
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        return self._send(404, {"error": "not found"})

    def _static(self, name):
        safe = os.path.normpath(name).replace("..", "")
        fpath = os.path.join(STATIC_DIR, safe)
        if not os.path.isfile(fpath):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(fpath)[1]
        with open(fpath, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()
        if path == "/api/games":
            try:
                n = int(body.get("players", 2))
            except Exception:
                n = 2
            n = max(2, min(4, n))
            bots = body.get("bots", [])
            if isinstance(body.get("botCount"), int):
                bots = list(range(1, 1 + max(0, min(n - 1, body["botCount"]))))
            bots = [b for b in bots if 0 <= b < n]
            if 0 in bots:
                bots = [b for b in bots if b != 0]
            name = str(body.get("name", "Player 1"))[:24] or "Player 1"
            with LOCK:
                game = new_game(n, bots, name)
                GAMES[game["id"]] = game
                token = "".join(random.choices(string.ascii_letters + string.digits, k=20))
                game["tokens"][0] = token
                save_store()
            out = public_state(game)
            out["yourPlayer"] = 0
            out["yourToken"] = token
            return self._send(201, out)
        if path.startswith("/api/games/"):
            parts = path.split("/")
            if len(parts) == 5 and parts[4] == "join":
                g = self._game(parts[3])
                if g is None:
                    return self._send(404, {"error": "game not found"})
                kind = "bot" if body.get("kind") == "bot" else "human"
                name = str(body.get("name", ""))[:24]
                with LOCK:
                    free = [p for p in g["players"]
                            if p["kind"] == "human" and not p.get("seated")]
                    if not free:
                        return self._send(409, {"error": "no free seats"})
                    seat = free[0]
                    seat["name"] = name or f"Player {seat['index'] + 1}"
                    seat["kind"] = kind
                    seat["seated"] = True
                    if g["status"] == "lobby" and all_seated(g):
                        g["status"] = "playing"
                    token = "".join(random.choices(string.ascii_letters + string.digits, k=20))
                    g["tokens"][seat["index"]] = token
                    save_store()
                out = public_state(g)
                out["yourPlayer"] = seat["index"]
                out["yourToken"] = token
                return self._send(200, out)
            if len(parts) == 5 and parts[4] == "move":
                g = self._game(parts[3])
                if g is None:
                    return self._send(404, {"error": "game not found"})
                try:
                    p = int(body.get("player"))
                    r = int(body.get("row"))
                    c = int(body.get("col"))
                except Exception:
                    return self._send(400, {"error": "player, row and col must be integers"})
                with LOCK:
                    if p not in g["tokens"] or g["tokens"][p] != body.get("token"):
                        return self._send(403, {"error": "bad or missing token for that seat"})
                    ok, err, flipped = apply_move(g, p, r, c)
                    save_store()
                if not ok:
                    return self._send(400, {"error": err, "state": public_state(g)})
                return self._send(200, public_state(g))
        return self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()


API_DOCS = {
    "name": "Lantern Conquest",
    "version": "1.0",
    "base": "same origin as the game page (or https://lamplightpay.com/conquest/)",
    "rules": "7x7 board, 2-4 players. Place a stone on an empty cell orthogonally adjacent to one of your stones; enemy stones in a straight line between your new stone and another of yours flip to your colour. No legal placement = pass. Most stones when the board fills or everyone passes wins.",
    "endpoints": [
        {"method": "GET", "path": "/api/games", "desc": "List games (id, code, status)."},
        {"method": "POST", "path": "/api/games", "body": {"players": "2-4 (default 2)", "botCount": "0-3 bots filling seats 1..n (default 1)", "name": "your display name"},
         "desc": "Create a game. You take seat 0 and get yourToken. Returns the full state."},
        {"method": "GET", "path": "/api/games/{id}", "desc": "Full game state: board (0 empty, 1-4 player), current player, scores, status, winner, log."},
        {"method": "GET", "path": "/api/games/{id}/log", "desc": "Move history / replay log."},
        {"method": "POST", "path": "/api/games/{id}/join", "body": {"name": "display name", "kind": "'human' or 'bot'"},
         "desc": "Take the next free seat. Returns yourPlayer and yourToken. Bot seats are played by the server automatically; external bots join as kind=bot and play via /move."},
        {"method": "POST", "path": "/api/games/{id}/move", "body": {"player": "your seat index", "token": "yourToken", "row": 0, "col": 0},
         "desc": "Place a stone. 400 + error on an illegal move; the state is returned either way."},
    ],
    "notes": "IDs and 4-letter lobby codes both work in the URL. All responses are JSON. No login; a seat token is the only auth. See bot.py in the repo for a complete sample bot.",
}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8898)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    load_store()
    threading.Thread(target=bot_worker, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Lantern Conquest on http://{args.host}:{args.port} ({len(GAMES)} games loaded)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
