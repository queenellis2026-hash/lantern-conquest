#!/usr/bin/env python3
"""Reasoning agent player for Lantern Conquest — SERV Hackathon prototype.

Plays Lantern Conquest through the public agent API, choosing every move
with an explicit, inspectable reasoning step:

  1. enumerate every legal move;
  2. simulate each move on a board copy;
  3. score it on named factors — immediate flips, positional value
     (corner/edge), corner-gift danger, the opponent's best one-move reply
     (a 1-ply lookahead), post-move mobility for both sides, and — in the
     endgame — raw stone differential;
  4. pick the best score (deterministic tie-break) and write a short
     written rationale for the choice, including why the runner-up lost,
     to the rationale log.

In a production SERV entry this local heuristic+rationale step is the seam
where SERV Reasoning plugs in: the same candidate set and factor scores are
handed to the reasoning service, and its returned rationale is logged in
exactly the same format (see README.md "Mapping to the real SERV entry").

Usage:
    python3 player.py --base http://127.0.0.1:8899 --create --bots 1
    python3 player.py --base http://127.0.0.1:8899 --join ABCD
    python3 player.py --base http://127.0.0.1:8899 --create --bots 0 --name Reasoner-A

Notes on seat kind: this agent joins/creates as kind "human". That is
deliberate and within the API rules (the seat is played by its token
holder either way): the server's bot_worker auto-plays any seat marked
kind "bot" — including externally-joined ones — which would race this
agent and make its moves for it. A reasoning agent must own its seat.
"""
import argparse
import json
import time
import urllib.request

SIZE = 7
DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
CORNERS = {(0, 0), (0, SIZE - 1), (SIZE - 1, 0), (SIZE - 1, SIZE - 1)}


# ---------------------------------------------------------------- transport
def call(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                base + path, data=data,
                headers={"Content-Type": "application/json"},
                method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r), None
        except urllib.error.HTTPError as e:
            try:
                return json.load(e), None  # API returns JSON error bodies
            except Exception:  # noqa: BLE001
                last = e
        except Exception as e:  # noqa: BLE001 - transient transport failure
            last = e
        time.sleep(0.5 * (attempt + 1))
    raise last


# ---------------------------------------------------------------- game rules
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


def apply(board, p, r, c):
    nb = [row[:] for row in board]
    nb[r][c] = p + 1
    for fr, fc in flips_for(board, p, r, c):
        nb[fr][fc] = p + 1
    return nb


def stone_counts(board, n):
    s = [0] * n
    for row in board:
        for v in row:
            if v:
                s[v - 1] += 1
    return s


# ---------------------------------------------------------------- reasoning
W = {
    "flip": 10.0,          # per stone flipped right now
    "corner": 50.0,        # taking a corner outright
    "edge": 5.0,           # any other edge cell
    "corner_gift": -16.0,  # playing next to a still-empty corner
    "opp_reply_flip": -6.0,  # per stone the best opponent reply can flip
    "opp_corner": -25.0,   # opponent can take a corner on their reply
    "mobility": 1.5,       # per move of (my mobility - best opp mobility)
    "endgame_diff": 3.0,   # per stone of differential once board is nearly full
}
ENDGAME_EMPTIES = 8


def evaluate(board, p, n_players):
    """Score every legal move for player p. Returns a list of candidate
    dicts (best first), each carrying its factor breakdown and the numbers
    the rationale is written from."""
    opp_indexes = [i for i in range(n_players) if i != p]
    empties = sum(v == 0 for row in board for v in row)
    out = []
    for (r, c) in legal_moves(board, p):
        flips = flips_for(board, p, r, c)
        nb = apply(board, p, r, c)
        counts = stone_counts(nb, n_players)

        f = {}
        f["flips"] = W["flip"] * len(flips)
        f["position"] = (W["corner"] if (r, c) in CORNERS else
                         W["edge"] if r in (0, SIZE - 1) or c in (0, SIZE - 1) else 0.0)
        f["corner_gift"] = 0.0
        if (r, c) not in CORNERS:
            for cr, cc in CORNERS:
                if abs(r - cr) + abs(c - cc) == 1 and nb[cr][cc] == 0:
                    f["corner_gift"] = W["corner_gift"]
        # 1-ply lookahead: the strongest reply any single opponent has
        opp_best_flips, opp_takes_corner, opp_mobility = 0, False, 0
        for o in opp_indexes:
            if counts[o] == 0:
                continue  # eliminated opponents have no reply
            om = legal_moves(nb, o)
            opp_mobility = max(opp_mobility, len(om))
            for (orr, occ) in om:
                opp_best_flips = max(opp_best_flips, len(flips_for(nb, o, orr, occ)))
                if (orr, occ) in CORNERS:
                    opp_takes_corner = True
        f["opp_reply"] = W["opp_reply_flip"] * opp_best_flips
        if opp_takes_corner:
            f["opp_reply"] += W["opp_corner"]
        my_mobility = len(legal_moves(nb, p))
        f["mobility"] = W["mobility"] * (my_mobility - opp_mobility)
        f["endgame"] = 0.0
        if empties - 1 <= ENDGAME_EMPTIES:
            best_opp = max((counts[o] for o in opp_indexes), default=0)
            f["endgame"] = W["endgame_diff"] * (counts[p] - best_opp)

        out.append({
            "move": (r, c), "score": sum(f.values()), "factors": f,
            "n_flips": len(flips),
            "opp_best_flips": opp_best_flips, "opp_takes_corner": opp_takes_corner,
            "my_mobility": my_mobility, "opp_mobility": opp_mobility,
            "counts_after": counts,
        })
    # deterministic: score desc, then board order
    out.sort(key=lambda d: (-d["score"], d["move"]))
    return out


def rationale(cands, p, turn):
    """Write the human-readable reason for the chosen move."""
    best = cands[0]
    r, c = best["move"]
    f = best["factors"]
    bits = []
    if best["n_flips"]:
        bits.append(f"flips {best['n_flips']} stone(s) now")
    else:
        bits.append("flips nothing — a positional move")
    if (r, c) in CORNERS:
        bits.append("takes a corner, which can never be flipped")
    elif f["position"]:
        bits.append("claims an edge cell")
    if f["corner_gift"]:
        bits.append("RISK: sits next to an empty corner")
    bits.append(f"opponent's best reply flips {best['opp_best_flips']}"
                + (" and can take a corner" if best["opp_takes_corner"] else ""))
    bits.append(f"mobility after: me {best['my_mobility']}, best opponent {best['opp_mobility']}")
    if f["endgame"]:
        bits.append(f"endgame: stone differential term {f['endgame']:+.0f}")
    txt = (f"turn {turn}: play ({r + 1},{c + 1}) [score {best['score']:.1f}] — "
           + "; ".join(bits) + ".")
    if len(cands) > 1:
        alt = cands[1]
        ar, ac = alt["move"]
        if alt["score"] == best["score"]:
            txt += (f" Runner-up ({ar + 1},{ac + 1}) tied at {alt['score']:.1f}; "
                    f"deterministic board order broke the tie.")
        else:
            weak = min(alt["factors"], key=alt["factors"].get)
            txt += (f" Runner-up ({ar + 1},{ac + 1}) [score {alt['score']:.1f}] lost mainly on "
                    f"'{weak}' ({alt['factors'][weak]:+.1f}).")
    txt += f" ({len(cands)} legal move(s) considered.)"
    return txt


# ---------------------------------------------------------------- agent loop
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    ap.add_argument("--name", default="Reasoner")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--bots", type=int, default=1,
                    help="server-bot seats when creating (bot.py's brain)")
    ap.add_argument("--join", metavar="CODE", help="join an existing game id/code")
    ap.add_argument("--rationale-log", default=None)
    ap.add_argument("--poll", type=float, default=0.7)
    ap.add_argument("--max-seconds", type=int, default=600)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    logf = open(args.rationale_log, "a") if args.rationale_log else None

    def log(msg):
        print(msg, flush=True)
        if logf:
            logf.write(msg + "\n")
            logf.flush()

    if args.join:
        g, err = call(base, f"/api/games/{args.join}/join",
                      {"name": args.name, "kind": "human"})
    else:
        g, err = call(base, "/api/games",
                      {"players": args.players, "botCount": args.bots, "name": args.name})
    if not g or "yourToken" not in g:
        raise SystemExit(f"could not enter a game: {g}")
    gid, me, token = g["id"], g["yourPlayer"], g["yourToken"]
    n_players = len(g["players"])
    log(f"[{args.name}] in game {gid} (code {g['code']}) as seat {me}; "
        f"game id for the record: {gid}")

    errors = 0
    my_moves = 0
    deadline = time.time() + args.max_seconds
    while time.time() < deadline:
        st, _ = call(base, f"/api/games/{gid}")
        if st["status"] == "finished":
            w = st["winner"]
            log(f"[{args.name}] game {gid} finished: winner="
                f"{'draw' if w == 'draw' else st['players'][w]['name']} scores={st['scores']}")
            print(json.dumps({"game": gid, "code": st["code"], "winner": w,
                              "scores": st["scores"], "my_moves": my_moves,
                              "api_errors": errors, "seat": me}))
            return
        if st["status"] != "playing" or st["current"] != me:
            time.sleep(args.poll)
            continue
        cands = evaluate(st["board"], me, n_players)
        if not cands:
            time.sleep(args.poll)  # server advances past a seat with no move
            continue
        best = cands[0]
        r, c = best["move"]
        log(f"[{args.name}] {rationale(cands, me, st['turn'])}")
        resp, _ = call(base, f"/api/games/{gid}/move",
                       {"player": me, "token": token, "row": r, "col": c})
        if resp and "error" in resp:
            errors += 1
            log(f"[{args.name}] MOVE REJECTED ({resp['error']}) — re-reading state")
            time.sleep(args.poll)
            continue
        my_moves += 1
    raise SystemExit(f"timed out after {args.max_seconds}s (moves={my_moves}, errors={errors})")


if __name__ == "__main__":
    main()
