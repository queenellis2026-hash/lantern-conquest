#!/usr/bin/env python3
"""Exact in-process replica of Lantern Conquest's rules (repo/server.py),
plus an exact replica of the server's built-in bot brain (bot_choose ==
bot.py's choose). Used for fast tuning; validated move-for-move against
the HTTP proof-game evidence before any result is trusted.

Board representation: a flat list of 49 ints (0 = empty, 1..n = player+1),
index = row * 7 + col. All functions are pure w.r.t. their board argument
except do_move/undo_move, which mutate and restore.

Semantics replicated from server.py, in order:
  * legal move: empty cell orthogonally adjacent to one of your stones;
  * flips: in each of 8 directions, a contiguous line of non-you, non-empty
    stones terminated by one of yours flips (the line may mix opponents
    in multiplayer; in 2-player games it is just the opponent);
  * after a move: a player on 0 stones is eliminated; if exactly one
    player still has stones the game finishes with that player as winner;
    else if the board is full the game finishes by score; else the turn
    passes to the next player (cyclically, possibly the mover again) who
    has stones and at least one legal move; if nobody can move the game
    finishes by score (most stones wins, tie = draw).
"""
import os
import sys

SIZE = 7
N = SIZE * SIZE
DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
CORNERS = (0, 6, 42, 48)
CORNERS_SET = frozenset(CORNERS)
STARTS = [(0, 0), (6, 6), (0, 6), (6, 0)]  # (row, col) per player index

# Precomputed rays: RAYS[cell][d] = tuple of cells along direction d.
RAYS = []
for r in range(SIZE):
    for c in range(SIZE):
        per_dir = []
        for dr, dc in DIRS:
            ray = []
            nr, nc = r + dr, c + dc
            while 0 <= nr < SIZE and 0 <= nc < SIZE:
                ray.append(nr * SIZE + nc)
                nr += dr
                nc += dc
            per_dir.append(tuple(ray))
        RAYS.append(tuple(per_dir))

# Orthogonal neighbours per cell.
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
                 if (i // SIZE) in (0, SIZE - 1) or (i % SIZE) in (0, SIZE - 1))


def idx(r, c):
    return r * SIZE + c


def rc(i):
    return divmod(i, SIZE)


def new_board(n_players=2):
    b = [0] * N
    for p in range(n_players):
        r, c = STARTS[p]
        b[idx(r, c)] = p + 1
    return b


def to7(flat):
    return [flat[r * SIZE:(r + 1) * SIZE] for r in range(SIZE)]


def from7(board7):
    return [v for row in board7 for v in row]


def legal_moves(board, p):
    """Cells (flat indexes, row-major order) where p may play."""
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
    """Cells that playing at i would flip for p (does not mutate)."""
    me = p + 1
    out = []
    for ray in RAYS[i]:
        line = []
        for j in ray:
            v = board[j]
            if v == 0:
                line = None
                break
            if v == me:
                break
            line.append(j)
        else:
            line = None  # ran off the edge without a bracket
        if line:
            out.extend(line)
    return out


def do_move(board, p, i):
    """Apply p's move at i in place. Returns the list of flipped cells
    (pass it to undo_move to restore). Assumes the move is legal."""
    flips = flips_for(board, p, i)
    me = p + 1
    board[i] = me
    for j in flips:
        board[j] = me
    return flips


def undo_move(board, p, i, flips, n_players=2):
    """Restore board after do_move. Flipped cells go back to their owner —
    in 2-player games that is always the single opponent; the server flips
    mixed lines in multiplayer, so for n>2 callers must snapshot instead.
    Only used with n_players=2 in this harness."""
    assert n_players == 2
    opp = 2 if p == 0 else 1
    board[i] = 0
    for j in flips:
        board[j] = opp


def stone_counts(board, n_players):
    s = [0] * n_players
    for v in board:
        if v:
            s[v - 1] += 1
    return s


def empties(board):
    return board.count(0)


class State:
    """A game position: board + counts + side to move + finished/winner."""

    __slots__ = ("board", "counts", "n", "current", "finished", "winner")

    def __init__(self, board, n_players=2, current=0):
        self.board = board
        self.n = n_players
        self.counts = stone_counts(board, n_players)
        self.current = current
        self.finished = False
        self.winner = None  # player index, "draw", or None while playing

    def clone(self):
        s = State.__new__(State)
        s.board = self.board[:]
        s.counts = self.counts[:]
        s.n = self.n
        s.current = self.current
        s.finished = self.finished
        s.winner = self.winner
        return s


def _finish_by_score(state):
    state.finished = True
    top = max(state.counts)
    winners = [i for i, s in enumerate(state.counts) if s == top]
    state.winner = winners[0] if len(winners) == 1 else "draw"


def advance(state):
    """Replicates server.advance(): set state.current to the next player
    who can move, or finish the game."""
    n = state.n
    alive = [i for i in range(n) if state.counts[i] > 0]
    if len(alive) == 1:
        state.finished = True
        state.winner = alive[0]
        return
    if empties(state.board) == 0:
        _finish_by_score(state)
        return
    for step in range(1, n + 1):
        nxt = (state.current + step) % n
        if state.counts[nxt] > 0 and legal_moves(state.board, nxt):
            state.current = nxt
            return
    _finish_by_score(state)


def play(state, i):
    """Play state.current's move at flat index i (assumed legal), update
    counts, and advance the turn exactly as the server does."""
    p = state.current
    flips = do_move(state.board, p, i)
    state.counts = stone_counts(state.board, state.n)
    advance(state)
    return flips


# ---------------------------------------------------------------- the bot
def bot_score(board, p, i):
    """bot_choose's score for one move (server.py / bot.py, verbatim math)."""
    s = len(flips_for(board, p, i)) * 10
    if i in CORNERS_SET:
        s += 60
    elif i in EDGE:
        s += 6
    r, c = rc(i)
    for corner in CORNERS:
        cr, cc = rc(corner)
        if abs(r - cr) + abs(c - cc) == 1 and board[corner] == 0:
            s -= 18
    return s


def bot_choose(board, p):
    """Exact replica of the server's built-in bot: max bot_score, first
    move in row-major order wins ties (strict > comparison)."""
    best, best_score = None, None
    for i in legal_moves(board, p):
        s = bot_score(board, p, i)
        if best_score is None or s > best_score:
            best, best_score = i, s
    return best


# ------------------------------------------------------- reference imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "repo"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def ref_bot_choose7(board7, p):
    """The repo's own bot.py choose(), on a 7x7 board — ground truth."""
    import bot as ref_bot
    mv = ref_bot.choose(board7, p)
    return None if mv is None else idx(mv[0], mv[1])


def v1_choose7(board7, p, n_players=2):
    """player.py's (v1) evaluate() top pick, on a 7x7 board."""
    import player as v1
    cands = v1.evaluate(board7, p, n_players)
    if not cands:
        return None
    r, c = cands[0]["move"]
    return idx(r, c)
