#!/usr/bin/env python3
"""Reasoning agent v3 for Lantern Conquest — tuned search player.

The tuned final version of the v2 search design (v2's docstring describes
the architecture; TUNING.md documents how this configuration was chosen
and the full scoreboard record). Identical to player_v2.py except that
DEFAULT_PARAMS now carries the tuned values: deeper search (5/6/7 plies
by phase, exact solve from 14 empties) with the original horizon weights
— a scoreboard sweep found those weights better than the variants tried,
and deeper settings (6/7/8, solve at 16) doubled the compute for no gain.

Final honest strength (full record in TUNING.md): on the 18-game
held-out scoreboard (canonical game + 8 seeded openings, both seats)
v3 went 18W-0D-0L with aggregate margin +228; across every board run
(tuning, held-out, alternate opening depths, HTTP) it is 54-0-0
against the sample bot, including both HTTP validation games won
with 0 API errors. The opponent is a 1-ply greedy — TUNING.md states
plainly what that does and does not prove.

Same public-API play and rationale discipline as player.py (v1), but the
1-ply factor heuristic is replaced by an alpha-beta search over the exact
game rules, with an exact endgame solver:

  1. enumerate every legal move;
  2. search each one with alpha-beta (transposition table, corner-first
     move ordering), the opponent modelled as a strong adversary
     (negamax) rather than a fixed script;
  3. at the horizon, score the position on named factors — stone
     differential, mobility, corner occupancy, corner access (owning a
     stone next to a still-empty corner is the only way in), edge stones;
  4. when few squares remain, stop estimating and SOLVE the position
     exactly: the value is the true final stone differential;
  5. write a rationale for the chosen move from the search result and
     the factor comparison against the runner-up.

Why this shape: v1's hand-weighted safety/mobility terms, applied one ply
deep, steered it off the line that demonstrably wins (see TUNING.md).
Search lets those same factors speak at the horizon instead of shouting
over the tactics.

Usage: identical CLI to player.py —
    python3 player_v3.py --base http://127.0.0.1:8899 --create --bots 1
    python3 player_v3.py --base http://127.0.0.1:8899 --join ABCD

Seat kind "human" for the same reason as v1: the server's bot_worker
auto-plays any seat marked "bot"; a reasoning agent must own its seat.
"""
import argparse
import json
import os
import time
import urllib.request

try:
    from serv_reason import ServReasoner
except ImportError:  # serv_reason.py not beside this file: SERV stays off
    ServReasoner = None

SIZE = 7
N = SIZE * SIZE
DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
CORNERS = (0, 6, 42, 48)
CORNERS_SET = frozenset(CORNERS)
# orthogonal neighbours of each corner — owning one is "corner access"
CORNER_NEIGHBORS = {0: (1, 7), 6: (5, 13), 42: (35, 43), 48: (41, 47)}

RAYS = []
for r in range(SIZE):
    for c in range(SIZE):
        per = []
        for dr, dc in DIRS:
            ray = []
            nr, nc = r + dr, c + dc
            while 0 <= nr < SIZE and 0 <= nc < SIZE:
                ray.append(nr * SIZE + nc)
                nr += dr
                nc += dc
            per.append(tuple(ray))
        RAYS.append(tuple(per))
ORTH = []
for r in range(SIZE):
    for c in range(SIZE):
        ns = []
        for dr, dc in ORTHO:
            nr, nc = r + dr, c + dc
            if 0 <= nr < SIZE and 0 <= nc < SIZE:
                ns.append(nr * SIZE + nc)
        ORTH.append(tuple(ns))
EDGE = frozenset(i for i in range(N)
                 if i // SIZE in (0, SIZE - 1) or i % SIZE in (0, SIZE - 1))

WIN = 100000.0  # terminal scale: any forced win beats any horizon eval

DEFAULT_PARAMS = {
    # horizon evaluation weights (differences: mine - opponent's)
    "w_diff": 1.0,       # stone differential
    "w_mob": 7.0,        # mobility (legal-move count)
    "w_corner": 300.0,   # corner occupancy — a corner can never be flipped
    "w_access": 25.0,    # corner access stones next to an empty corner
    "w_edge": 2.0,       # edge stones (fewer lines run through them)
    # depth schedule by empties remaining (tuned: see TUNING.md)
    "depth_far": 5,      # empties > 30
    "depth_mid": 6,      # 21..30
    "depth_near": 7,     # solve_at < empties <= 20
    "solve_at": 14,      # empties <= solve_at: exact solve to the end
}


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
                return json.load(e), None
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
    for i in range(N):
        if board[i] != 0:
            continue
        for nb in ORTH[i]:
            if board[nb] == me:
                out.append(i)
                break
    return out


def flips_for(board, p, i):
    me = p + 1
    out = []
    for ray in RAYS[i]:
        line = []
        hit = False
        for j in ray:
            v = board[j]
            if v == 0:
                line = []
                break
            if v == me:
                hit = True
                break
            line.append(j)
        if hit:
            out.extend(line)
    return out


def do_move(board, counts, p, i):
    flips = flips_for(board, p, i)
    me = p + 1
    board[i] = me
    for j in flips:
        board[j] = me
    counts[p] += 1 + len(flips)
    counts[1 - p] -= len(flips)
    return flips


def undo_move(board, counts, p, i, flips):
    opp = 2 if p == 0 else 1
    board[i] = 0
    for j in flips:
        board[j] = opp
    counts[p] -= 1 + len(flips)
    counts[1 - p] += len(flips)


def stone_counts(board):
    s = [0, 0]
    for v in board:
        if v:
            s[v - 1] += 1
    return s


# ---------------------------------------------------------------- evaluation
def corner_access(board, p):
    """Net corner-access stones for p: for each empty corner, my stones on
    its two orthogonal neighbours minus the opponent's."""
    me, opp = p + 1, 2 - p
    total = 0
    for corner in CORNERS:
        if board[corner] != 0:
            continue
        for nb in CORNER_NEIGHBORS[corner]:
            if board[nb] == me:
                total += 1
            elif board[nb] == opp:
                total -= 1
    return total


def evaluate(board, counts, side, W):
    """Horizon score of a non-terminal position, from `side`'s perspective.
    Every term is a named factor; the rationale quotes these by name."""
    opp = 1 - side
    me, op = side + 1, opp + 1
    diff = counts[side] - counts[opp]
    mob = len(legal_moves(board, side)) - len(legal_moves(board, opp))
    corners = sum(1 for cn in CORNERS if board[cn] == me) \
        - sum(1 for cn in CORNERS if board[cn] == op)
    access = corner_access(board, side)
    edges = sum(1 for i in EDGE if board[i] == me) \
        - sum(1 for i in EDGE if board[i] == op)
    return (W["w_diff"] * diff + W["w_mob"] * mob + W["w_corner"] * corners
            + W["w_access"] * access + W["w_edge"] * edges)


def _terminal(counts, persp):
    diff = counts[persp] - counts[1 - persp]
    if diff > 0:
        return WIN + diff * 100.0
    if diff < 0:
        return -WIN + diff * 100.0
    return 0.0


def _ordered(board, p, moves, tt_move=None):
    """Corner takes first, then most flips, then board order — cheap and
    effective alpha-beta ordering."""
    def key(i):
        return (0 if i in CORNERS_SET else 1, -len(flips_for(board, p, i)), i)
    moves.sort(key=key)
    if tt_move is not None and tt_move in moves:
        moves.remove(tt_move)
        moves.insert(0, tt_move)
    return moves


def _after_move(board, counts, mover, depth, alpha, beta, tt, W):
    """Value of the position right after `mover` moved, from mover's
    perspective. Applies the server's advance rule: the opponent moves
    next if it can, else the mover moves again, else the game is over."""
    opp = 1 - mover
    if counts[opp] == 0 or counts[mover] == 0 or counts[0] + counts[1] == N:
        return _terminal(counts, mover)
    if legal_moves(board, opp):
        return -_ab(board, counts, opp, depth, -beta, -alpha, tt, W)
    if legal_moves(board, mover):
        return _ab(board, counts, mover, depth, alpha, beta, tt, W)
    return _terminal(counts, mover)


def _ab(board, counts, side, depth, alpha, beta, tt, W):
    """Alpha-beta value from `side`'s perspective. Precondition: the game
    is not finished and `side` has at least one legal move."""
    if depth <= 0:
        return evaluate(board, counts, side, W)
    alpha_orig, beta_orig = alpha, beta
    key = None
    tt_move = None
    if tt is not None:
        key = (bytes(board), side, depth)
        hit = tt.get(key)
        if hit is not None:
            val, flag, tt_move = hit
            if flag == 0:
                return val
            if flag == 1:  # lower bound
                alpha = max(alpha, val)
            else:  # upper bound
                beta = min(beta, val)
            if alpha >= beta:
                return val
    moves = _ordered(board, side, legal_moves(board, side), tt_move)
    best = -float("inf")
    best_move = moves[0]
    for mv in moves:
        flips = do_move(board, counts, side, mv)
        v = _after_move(board, counts, side, depth - 1, alpha, beta, tt, W)
        undo_move(board, counts, side, mv, flips)
        if v > best:
            best, best_move = v, mv
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    if tt is not None:
        # label bounds against the window this call was given, never the
        # TT-tightened one — otherwise a bound can be stored as "exact"
        flag = 2 if best <= alpha_orig else (1 if best >= beta_orig else 0)
        tt[key] = (best, flag, best_move)
    return best


def _depth_for(empt, P):
    if empt <= P["solve_at"]:
        return empt + 8  # exact solve: terminal checks end the recursion
    if empt > 30:
        return P["depth_far"]
    if empt > 20:
        return P["depth_mid"]
    return P["depth_near"]


def _root_factors(board, p, mv, flips, child_board, child_counts, solved):
    """Named-factor snapshot of a root move, for the rationale."""
    opp = 1 - p
    opp_moves = legal_moves(child_board, opp)
    opp_best = 0
    opp_corner = False
    for om in opp_moves:
        opp_best = max(opp_best, len(flips_for(child_board, opp, om)))
        if om in CORNERS_SET:
            opp_corner = True
    return {
        "move": mv,
        "flips": len(flips),
        "corner": mv in CORNERS_SET,
        "my_mobility": len(legal_moves(child_board, p)),
        "opp_mobility": len(opp_moves),
        "opp_best_reply_flips": opp_best,
        "opp_can_take_corner": opp_corner,
        "corner_access_after": corner_access(child_board, p),
        "counts_after": list(child_counts),
        "solved_final_diff": (child_counts[p] - child_counts[opp]) if solved else None,
    }


def decide(board, p, n_players=2, params=None):
    """Pick a move on a flat 49-cell board for player p.

    Returns (move_index, report) where report carries the root candidate
    list (best first) with search values and factor snapshots — the raw
    material for the rationale. Returns (None, report) if p has no move.
    """
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    counts = stone_counts(board)
    moves = legal_moves(board, p)
    report = {"params": P, "candidates": [], "solved": False}
    if not moves:
        return None, report
    if n_players != 2:
        return _decide_multi(board, p, n_players, moves, report)
    empt = board.count(0)
    depth = _depth_for(empt, P)
    report["solved"] = empt <= P["solve_at"]
    report["depth"] = depth
    tt = {}
    cands = []
    # Evaluate every root move with a full window so the rationale can
    # compare the winner and the runner-up honestly.
    for mv in _ordered(board, p, moves[:]):
        flips = do_move(board, counts, p, mv)
        v = _after_move(board, counts, p, depth - 1,
                        -float("inf"), float("inf"), tt, P)
        fac = _root_factors(board, p, mv, flips, board, counts, report["solved"])
        undo_move(board, counts, p, mv, flips)
        fac["value"] = v
        cands.append(fac)
    cands.sort(key=lambda d: (-d["value"], d["move"]))
    report["candidates"] = cands
    return cands[0]["move"], report


def _decide_multi(board, p, n_players, moves, report):
    """Fallback for 3-4 player seats (the search is a 2-player search):
    greedy flips with corner/edge terms and a corner-gift penalty, the
    house style. Documented as a fallback in TUNING.md."""
    counts = [0] * n_players
    for v in board:
        if v:
            counts[v - 1] += 1
    cands = []
    for mv in moves:
        flips = flips_for(board, p, mv)
        s = len(flips) * 10.0
        if mv in CORNERS_SET:
            s += 60.0
        elif mv in EDGE:
            s += 6.0
        r, c = divmod(mv, SIZE)
        for corner in CORNERS:
            cr, cc = divmod(corner, SIZE)
            if abs(r - cr) + abs(c - cc) == 1 and board[corner] == 0:
                s -= 18.0
        cands.append({"move": mv, "value": s, "flips": len(flips),
                      "corner": mv in CORNERS_SET, "my_mobility": 0,
                      "opp_mobility": 0, "opp_best_reply_flips": 0,
                      "opp_can_take_corner": False, "corner_access_after": 0,
                      "counts_after": counts, "solved_final_diff": None})
    cands.sort(key=lambda d: (-d["value"], d["move"]))
    report["candidates"] = cands
    report["multiplayer_fallback"] = True
    return cands[0]["move"], report


# ---------------------------------------------------------------- rationale
def rationale(report, p, turn):
    """Write the reason for the chosen move from the search report."""
    cands = report["candidates"]
    best = cands[0]
    r, c = divmod(best["move"], SIZE)
    bits = []
    if report.get("solved"):
        bits.append(f"endgame solved exactly: this line ends "
                    f"{best['counts_after'][p]}-{best['counts_after'][1 - p]}")
    else:
        bits.append(f"search (depth {report.get('depth', '?')}) values it "
                    f"{best['value']:+.0f}")
    bits.append(f"flips {best['flips']} stone(s) now" if best["flips"]
                else "flips nothing — a positional move")
    if best["corner"]:
        bits.append("takes a corner, which can never be flipped")
    bits.append(f"corner access after: {best['corner_access_after']:+d}")
    bits.append(f"mobility after: me {best['my_mobility']}, "
                f"opponent {best['opp_mobility']}")
    bits.append(f"opponent's best reply flips {best['opp_best_reply_flips']}"
                + (" and can take a corner" if best["opp_can_take_corner"] else ""))
    txt = (f"turn {turn}: play ({r + 1},{c + 1}) [value {best['value']:+.0f}] — "
           + "; ".join(bits) + ".")
    if len(cands) > 1:
        alt = cands[1]
        ar, ac = divmod(alt["move"], SIZE)
        if alt["value"] == best["value"]:
            txt += (f" Runner-up ({ar + 1},{ac + 1}) tied at {alt['value']:+.0f}; "
                    f"deterministic order broke the tie.")
        else:
            # name the factor where the runner-up falls furthest behind
            deficits = []
            if alt["flips"] < best["flips"]:
                deficits.append(("immediate flips",
                                 best["flips"] - alt["flips"]))
            if best["corner"] and not alt["corner"]:
                deficits.append(("corner occupancy", 1))
            if alt["opp_best_reply_flips"] > best["opp_best_reply_flips"]:
                deficits.append(("opponent's best reply",
                                 alt["opp_best_reply_flips"] - best["opp_best_reply_flips"]))
            if alt["opp_mobility"] - alt["my_mobility"] > \
               best["opp_mobility"] - best["my_mobility"]:
                deficits.append(("mobility balance",
                                 (alt["opp_mobility"] - alt["my_mobility"])
                                 - (best["opp_mobility"] - best["my_mobility"])))
            if alt["corner_access_after"] < best["corner_access_after"]:
                deficits.append(("corner access",
                                 best["corner_access_after"] - alt["corner_access_after"]))
            if deficits:
                name, gap = max(deficits, key=lambda d: d[1])
                txt += (f" Runner-up ({ar + 1},{ac + 1}) [value {alt['value']:+.0f}] "
                        f"lost mainly on {name} (gap {gap}).")
            else:
                txt += (f" Runner-up ({ar + 1},{ac + 1}) [value {alt['value']:+.0f}] "
                        f"lost on the searched position as a whole — no single "
                        f"factor separates them.")
    txt += f" ({len(cands)} legal move(s) considered.)"
    return txt


# ------------------------------------------------------- harness interface
def choose_flat(board, p, params=None):
    """In-process entry point (tuning harness): flat board -> move index."""
    mv, _ = decide(board, p, 2, params)
    return mv


def board7_to_flat(board7):
    return [v for row in board7 for v in row]


# ---------------------------------------------------------------- agent loop
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    ap.add_argument("--name", default="ReasonerV3")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--bots", type=int, default=1)
    ap.add_argument("--join", metavar="CODE")
    ap.add_argument("--rationale-log", default=None)
    ap.add_argument("--poll", type=float, default=0.7)
    ap.add_argument("--max-seconds", type=int, default=900)
    ap.add_argument("--serv", action="store_true",
                    help="ask SERV Reasoning for each move (serv_reason.py); "
                         "falls back to the local search on any failure. "
                         "Needs SERV_API_KEY; also on with SERV_ENABLED=1.")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    logf = open(args.rationale_log, "a") if args.rationale_log else None
    serv = None
    if args.serv or os.environ.get("SERV_ENABLED") == "1":
        if ServReasoner is None:
            raise SystemExit("--serv needs serv_reason.py beside player_v3.py")
        serv = ServReasoner()
        if not serv.enabled:
            print("[ReasonerV3] --serv requested but SERV_API_KEY is not set; "
                  "playing local-only (SERV calls will fall back).", flush=True)

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
        board = board7_to_flat(st["board"])
        mv, report = decide(board, me, n_players)
        if mv is None:
            time.sleep(args.poll)
            continue
        if serv is not None:
            legal = [c["move"] for c in report["candidates"]]
            mv, serv_rat, source = serv.choose(
                board, legal, report["candidates"], me, st["turn"],
                fallback_move=mv)
            r, c = divmod(mv, SIZE)
            if source == "serv":
                local = report["candidates"][0]
                lr, lc = divmod(local["move"], SIZE)
                agree = "agrees with the local search" if local["move"] == mv \
                    else (f"overrules the local best ({lr + 1},{lc + 1}) "
                          f"[value {local['value']:+.0f}]")
                log(f"[{args.name}] turn {st['turn']}: play ({r + 1},{c + 1}) "
                    f"[SERV] — {serv_rat} ({agree}; "
                    f"{len(legal)} legal move(s) considered.)")
            else:
                log(f"[{args.name}] {rationale(report, me, st['turn'])} "
                    f"[local fallback: {serv_rat}]")
        else:
            log(f"[{args.name}] {rationale(report, me, st['turn'])}")
        r, c = divmod(mv, SIZE)
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
