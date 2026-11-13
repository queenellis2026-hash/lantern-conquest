#!/usr/bin/env python3
"""Validate tuning/engine.py against ground truth before trusting it:

1. bot_choose (flat replica) vs the repo's own bot.py choose() on random
   boards — must agree on every position.
2. Simulated Game A (v1 reasoner seat 0 vs built-in bot seat 1) vs
   evidence/gameA-server-log.json — every move, flip set, and running
   score must match; final 20-29, winner seat 1.
3. Simulated greedy baseline (sample-bot brain in both seats) — final
   must be 28-21, winner seat 0 (evidence/baseline-greedy-seat0.json).
4. Simulated Game B (v1 vs v1) — final must be 25-24, winner seat 0.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
EV = os.path.join(HERE, "..", "evidence")


def play_out(brain0, brain1, record=None):
    """brain: fn(state) -> flat move index for state.current."""
    st = E.State(E.new_board(2))
    brains = [brain0, brain1]
    while not st.finished:
        p = st.current
        mv = brains[p](st)
        assert mv is not None, f"brain for seat {p} returned no move"
        flips = E.play(st, mv)
        if record is not None:
            record.append({
                "player": p, "move": mv,
                "flipped": sorted(E.rc(j) for j in flips),
                "scores": list(st.counts),
            })
    return st


def brain_bot(st):
    return E.bot_choose(st.board, st.current)


def brain_v1(st):
    return E.v1_choose7(E.to7(st.board), st.current, 2)


def check_bot_replica(trials=400):
    rng = random.Random(12345)
    for t in range(trials):
        # random playout prefix -> a realistic mid-game board
        st = E.State(E.new_board(2))
        for _ in range(rng.randrange(0, 40)):
            if st.finished:
                break
            mv = rng.choice(E.legal_moves(st.board, st.current))
            E.play(st, mv)
        if st.finished:
            continue
        p = st.current
        mine = E.bot_choose(st.board, p)
        ref = E.ref_bot_choose7(E.to7(st.board), p)
        assert mine == ref, f"trial {t}: replica {mine} != repo bot {ref}"
    print(f"bot replica: agrees with repo bot.py on {trials} random positions")


def check_game_a():
    with open(os.path.join(EV, "gameA-server-log.json")) as f:
        ref_log = json.load(f)["log"]
    record = []
    st = play_out(brain_v1, brain_bot, record)
    assert len(record) == len(ref_log), \
        f"move count {len(record)} != server log {len(ref_log)}"
    for k, (mine, ref) in enumerate(zip(record, ref_log)):
        r, c = E.rc(mine["move"])
        assert mine["player"] == ref["player"], f"ply {k}: player differs"
        assert (r, c) == (ref["row"], ref["col"]), \
            f"ply {k}: move {(r, c)} != server {(ref['row'], ref['col'])}"
        ref_flips = sorted(tuple(x) for x in ref["flipped"])
        assert [tuple(x) for x in mine["flipped"]] == ref_flips, \
            f"ply {k}: flips differ"
        assert mine["scores"] == ref["scores"], f"ply {k}: scores differ"
    assert st.counts == [20, 29] and st.winner == 1, \
        f"Game A final {st.counts} winner {st.winner} != [20, 29] / 1"
    print("Game A: simulated v1-vs-bot matches the HTTP server log "
          "move-for-move (47 plies); final 20-29, bot wins")


def check_baseline():
    st = play_out(brain_bot, brain_bot)
    assert st.counts == [28, 21] and st.winner == 0, \
        f"baseline {st.counts} winner {st.winner} != [28, 21] / 0"
    print("Baseline: greedy-vs-greedy simulation ends 28-21, seat 0 wins "
          "(matches evidence/baseline-greedy-seat0.json)")


def check_game_b():
    st = play_out(brain_v1, brain_v1)
    assert st.counts == [25, 24] and st.winner == 0, \
        f"Game B {st.counts} winner {st.winner} != [25, 24] / 0"
    print("Game B: simulated v1-vs-v1 ends 25-24, seat 0 wins "
          "(matches evidence/gameB-final-state.json)")


if __name__ == "__main__":
    check_bot_replica()
    check_game_a()
    check_baseline()
    check_game_b()
    print("ENGINE VALIDATED")
