#!/usr/bin/env python3
"""Round-robin scoreboard: candidate player vs the sample bot (replica),
both seats, from seeded random opening prefixes (plus the canonical
no-prefix game), on the validated in-process engine.

Brains are modules exposing choose_flat(board_list49, seat, params) ->
flat move index. "bot" and "v1" are built in.

Usage:
    python3 harness.py --brain v2 --seeds 0-7 --prefix-plies 6 \
        [--param w_mob=9 --param depth_mid=6] [--out results/v2-a.json]
"""
import argparse
import importlib
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import engine as E

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load_brain(name, params):
    if name == "bot":
        return lambda board, seat: E.bot_choose(board, seat)
    if name == "v1":
        def v1_brain(board, seat):
            return E.v1_choose7(E.to7(board), seat, 2)
        return v1_brain
    mod = importlib.import_module(f"player_{name}")

    def brain(board, seat):
        return mod.choose_flat(board, seat, params)
    return brain


def prefix_state(seed, plies):
    """Play `plies` uniformly-random legal plies from the standard start
    with a seeded RNG; return the resulting State (side to move set by
    the engine's advance rule)."""
    rng = random.Random(seed)
    st = E.State(E.new_board(2))
    for _ in range(plies):
        if st.finished:
            break
        mv = rng.choice(E.legal_moves(st.board, st.current))
        E.play(st, mv)
    return st


def play_game(state, brain_cand, brain_bot, cand_seat):
    st = state.clone()
    brains = [brain_bot, brain_bot]
    brains[cand_seat] = brain_cand
    while not st.finished:
        mv = brains[st.current](st.board, st.current)
        assert mv is not None, "brain returned no move in a live position"
        E.play(st, mv)
    mine = st.counts[cand_seat]
    theirs = st.counts[1 - cand_seat]
    if st.winner == "draw":
        outcome = "D"
    elif st.winner == cand_seat:
        outcome = "W"
    else:
        outcome = "L"
    return {"seat": cand_seat, "outcome": outcome, "mine": mine,
            "theirs": theirs, "margin": mine - theirs}


def run_scoreboard(brain_name, seeds, prefix_plies, params=None,
                   canonical=True):
    brain_cand = load_brain(brain_name, params)
    brain_bot = load_brain("bot", None)
    games = []
    t0 = time.time()
    specs = []
    if canonical:
        specs.append(("canonical", None))
    for s in seeds:
        specs.append((f"seed{s}", s))
    for tag, seed in specs:
        base = E.State(E.new_board(2)) if seed is None \
            else prefix_state(seed, prefix_plies)
        for seat in (0, 1):
            g = play_game(base, brain_cand, brain_bot, seat)
            g["tag"] = tag
            games.append(g)
            print(f"  {tag:>10} seat{seat}: {g['outcome']} "
                  f"{g['mine']}-{g['theirs']} (margin {g['margin']:+d})",
                  flush=True)
    dt = time.time() - t0
    w = sum(1 for g in games if g["outcome"] == "W")
    d = sum(1 for g in games if g["outcome"] == "D")
    l = sum(1 for g in games if g["outcome"] == "L")
    agg = sum(g["margin"] for g in games)
    summary = {"brain": brain_name, "params": params, "games": len(games),
               "wins": w, "draws": d, "losses": l, "agg_margin": agg,
               "seconds": round(dt, 1), "detail": games}
    print(f"== {brain_name}: {w}W {d}D {l}L, aggregate margin {agg:+d}, "
          f"{dt:.1f}s ==")
    return summary


def parse_seeds(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default="v2")
    ap.add_argument("--seeds", default="0-7")
    ap.add_argument("--prefix-plies", type=int, default=6)
    ap.add_argument("--no-canonical", action="store_true")
    ap.add_argument("--param", action="append", default=[],
                    help="key=value override for the candidate's params")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    params = {}
    for kv in args.param:
        k, v = kv.split("=", 1)
        params[k] = float(v) if "." in v else int(v)
    summary = run_scoreboard(args.brain, parse_seeds(args.seeds),
                             args.prefix_plies, params or None,
                             canonical=not args.no_canonical)
    if args.out:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(summary, f, indent=2)
        print("wrote", path)


if __name__ == "__main__":
    main()
