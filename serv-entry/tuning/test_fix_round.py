#!/usr/bin/env python3
"""Fix-round tests for the SERV Grok-review fixes (Nov 8, 2026).

Run from src/serv-agent/:  python3 tuning/test_fix_round.py

Covers, with honest counts printed at the end:
  1. Solved rationale truth — "ends X-Y" is the true final score.
  2. Weighted runner-up deficits — mixed-unit max() is gone.
  3. Submission count correction — 52/+624, no 54 left in the docs.
  4. Multiplayer fallback disabled — decide() refuses, _decide_multi raises.
  5. Property checks — random positions: legal moves only, rationale
     never crashes, solved lines self-consistent.
  6. League file integrity — W+D+L adds up, margins match scores.

Exit code 0 only if every check passes; failures print and exit 1.
"""
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import engine as E
import player_v3 as P

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def random_position(seed, plies):
    rng = random.Random(seed)
    st = E.State(E.new_board(2))
    for _ in range(plies):
        if st.finished:
            break
        mv = rng.choice(E.legal_moves(st.board, st.current))
        E.play(st, mv)
    return st


def test_solved_rationale_truth():
    print("== Fix 1: solved rationale states the TRUE final score ==")
    # (a) value-derived diff == walked final diff, on solved positions
    for seed, plies in [(201, 33), (202, 35), (203, 37), (204, 34), (205, 36)]:
        st = random_position(seed, plies)
        if st.finished:
            continue
        board, p = st.board[:], st.current
        mv, rep = P.decide(board, p, 2)
        assert rep["solved"], f"seed {seed}: expected solved"
        best = rep["candidates"][0]
        fc = rep["final_counts"]
        check(f"seed {seed}: final_counts present",
              fc is not None)
        check(f"seed {seed}: stated diff == value-derived diff",
              fc[p] - fc[1 - p] == P._diff_from_value(best["value"]),
              f"walk {fc[p] - fc[1 - p]} vs value "
              f"{P._diff_from_value(best['value'])}")
        check(f"seed {seed}: final counts are a legal terminal total",
              0 <= fc[p] + fc[1 - p] <= 49,
              f"total {fc[p] + fc[1 - p]}")
        # every candidate's solved_final_diff must come from its value
        ok = all(c["solved_final_diff"] == P._diff_from_value(c["value"])
                 for c in rep["candidates"])
        check(f"seed {seed}: all candidates' solved_final_diff from value",
              ok)
        txt = P.rationale(rep, p, 1)
        m = re.search(r"this line ends (\d+)-(\d+)", txt)
        check(f"seed {seed}: rationale prints ends X-Y",
              m is not None, txt[:120])
        if m:
            check(f"seed {seed}: printed X-Y == final_counts",
                  int(m.group(1)) == fc[p] and int(m.group(2)) == fc[1 - p],
                  f"printed {m.group(1)}-{m.group(2)} vs {fc[p]}-{fc[1 - p]}")
    # (b) end-to-end: from a solved position, play BOTH sides with
    # decide() and the game must end exactly at the stated counts.
    st = random_position(206, 34)
    board, p = st.board[:], st.current
    mv, rep = P.decide(board, p, 2)
    stated = rep["final_counts"]
    b = board[:]
    c = P.stone_counts(b)
    side = p
    while True:
        if c[0] == 0 or c[1] == 0 or c[0] + c[1] == P.N:
            break
        m2, _ = P.decide(b, side, 2)
        assert m2 is not None
        P.do_move(b, c, side, m2)
        opp = 1 - side
        if P.legal_moves(b, opp):
            side = opp
        elif P.legal_moves(b, side):
            pass
        else:
            break
    check("end-to-end: optimal play from a solved position ends at the "
          "stated final counts", c == stated, f"played {c} vs stated {stated}")


def test_weighted_deficits():
    print("== Fix 2: runner-up deficit is weighted, not raw max() ==")
    # synthetic: corner gap 1 (worth 300) vs flips gap 5 (worth 10).
    # The old max() over raw gaps named "immediate flips" (5 > 1); the
    # weighted rule must name corner occupancy.
    W = dict(P.DEFAULT_PARAMS)
    best = {"flips": 5, "corner": True, "opp_best_reply_flips": 0,
            "opp_mobility": 3, "my_mobility": 5, "corner_access_after": 1,
            "solved_final_diff": None}
    alt = {"flips": 0, "corner": False, "opp_best_reply_flips": 0,
           "opp_mobility": 3, "my_mobility": 5, "corner_access_after": 1,
           "solved_final_diff": None}
    defs = P._weighted_deficits(best, alt, {"params": W, "solved": False})
    name, gap = max(defs, key=lambda d: d[1])
    check("corner gap 1 (300) beats flips gap 5 (10)",
          name == "corner occupancy", f"named {name} ({gap})")
    check("flips weighted at 2 per stone of differential",
          dict(defs).get("immediate flips") == 10.0,
          f"{dict(defs).get('immediate flips')}")
    # solved: a final-differential gap of 3 stones (300) must dominate
    best2 = dict(best, solved_final_diff=5)
    alt2 = dict(alt, solved_final_diff=2)
    defs2 = P._weighted_deficits(best2, alt2, {"params": W, "solved": True})
    name2, gap2 = max(defs2, key=lambda d: d[1])
    check("solved final differential gap is priced at 100/stone",
          ("solved final differential", 300.0) in defs2, f"{defs2}")
    # live: over real rationales, the named factor must be the weighted
    # argmax, and the sentence must carry the value-gap context.
    st = random_position(207, 20)
    board, p = st.board[:], st.current
    mv, rep = P.decide(board, p, 2)
    txt = P.rationale(rep, p, 1)
    if len(rep["candidates"]) > 1 and \
            rep["candidates"][1]["value"] != rep["candidates"][0]["value"]:
        defs3 = P._weighted_deficits(rep["candidates"][0],
                                     rep["candidates"][1], rep)
        if defs3:
            expect = max(defs3, key=lambda d: d[1])[0]
            check("live rationale names the weighted-argmax factor",
                  f"lost mainly on {expect}" in txt, txt[:200])
            check("live rationale states the value gap for context",
                  "of a " in txt and "value gap" in txt, txt[:200])
        else:
            check("live rationale falls back honestly when no factor "
                  "separates them",
                  "lost on the searched position as a whole" in txt,
                  txt[:200])


def test_count_correction():
    print("== Fix 3: submission count is 52/+624, no 54 left ==")
    for rel in ["player_v3.py", "TUNING.md", "README.md"]:
        text = open(os.path.join(ROOT, rel)).read()
        check(f"{rel}: no 54-0 / 54W / 54–0 claim",
              not re.search(r"54\s*[-–]\s*0|54W", text))
    sub = os.path.join(ROOT, "..", "..", "corrected-submission-text.md")
    check("corrected submission text exists", os.path.exists(sub))
    if os.path.exists(sub):
        text = open(sub).read()
        check("corrected text: no 54-0 / 54–0",
              not re.search(r"54\s*[-–]\s*0", text))
        check("corrected text: says 52", "52" in text)
        check("corrected text: says +624", "+624" in text)
    # the raw results must sum to 52/+624 (independent in-process games)
    tot_g = tot_m = 0
    for f in ["v3-heldout.json", "v3-plies4.json", "v3-plies10.json",
              "v2-deep.json"]:
        d = json.load(open(os.path.join(
            ROOT, "tuning", "results", f)))
        tot_g += d["games"]
        tot_m += d["agg_margin"]
    check("results JSONs sum to 52 games", tot_g == 52, f"got {tot_g}")
    check("results JSONs sum to +624", tot_m == 624, f"got {tot_m:+d}")


def test_multiplayer_disabled():
    print("== Fix 5: multiplayer fallback is disabled ==")
    st = random_position(208, 6)
    board, p = st.board[:], st.current
    mv, rep = P.decide(board, p, 3)
    check("decide() refuses a 3-player seat (returns None)",
          mv is None)
    check("refusal is flagged in the report",
          rep.get("multiplayer_disabled") is True)
    check("refusal names the discredited fallback",
          "discredited" in rep.get("error", ""), rep.get("error", ""))
    mv4, rep4 = P.decide(board, p, 4)
    check("decide() refuses a 4-player seat", mv4 is None)
    try:
        P._decide_multi(board, p, 3, P.legal_moves(board, p), rep)
        check("_decide_multi raises on direct call", False)
    except RuntimeError as e:
        check("_decide_multi raises on direct call", "DISCREDITED" in str(e),
              str(e)[:100])


def test_properties():
    print("== Property checks: random positions ==")
    rng = random.Random(99)
    n_solved_checked = 0
    for trial in range(30):
        seed = rng.randrange(10000)
        plies = rng.randrange(0, 42)
        st = random_position(seed, plies)
        if st.finished:
            continue
        board, p = st.board[:], st.current
        legal = P.legal_moves(board, p)
        mv, rep = P.decide(board, p, 2)
        if not legal:
            check(f"trial {trial}: no legal moves -> None", mv is None)
            continue
        check(f"trial {trial}: move is legal",
              mv in legal, f"move {mv} not in {legal}")
        txt = P.rationale(rep, p, 1)  # must not crash
        check(f"trial {trial}: rationale renders",
              isinstance(txt, str) and len(txt) > 0)
        if rep["solved"]:
            n_solved_checked += 1
            best = rep["candidates"][0]
            fc = rep["final_counts"]
            check(f"trial {trial} (solved): stated diff == value diff",
                  fc[p] - fc[1 - p] == P._diff_from_value(best["value"]))
    print(f"  (solved positions checked among the 30 trials: "
          f"{n_solved_checked})")
    check("at least 5 solved positions were exercised",
          n_solved_checked >= 5, f"got {n_solved_checked}")


def test_league_file():
    print("== League file integrity ==")
    path = os.path.join(ROOT, "tuning", "results",
                        "league-v3-vs-search.json")
    if not os.path.exists(path):
        print("  [SKIP] league results file not present yet "
              "(league still running?)")
        return
    d = json.load(open(path))
    check("league totals add up",
          d["games"] == d["v3_wins"] + d["draws"] + d["v3_losses"],
          f"{d['games']} vs {d['v3_wins']}+{d['draws']}+{d['v3_losses']}")
    for m in d["matchups"]:
        check(f"matchup {m['opponent']}: W+D+L == games",
              m["games"] == m["v3_wins"] + m["draws"] + m["v3_losses"])
        check(f"matchup {m['opponent']}: margins match scores",
              all(g["margin"] == g["mine"] - g["theirs"]
                  for g in m["detail"]))
        check(f"matchup {m['opponent']}: agg margin matches detail",
              m["v3_agg_margin"] == sum(g["margin"] for g in m["detail"]))
    print(f"  league: v3 {d['v3_wins']}W {d['draws']}D {d['v3_losses']}L "
          f"over {d['games']} games, aggregate {d['v3_agg_margin']:+d}")


if __name__ == "__main__":
    test_solved_rationale_truth()
    test_weighted_deficits()
    test_count_correction()
    test_multiplayer_disabled()
    test_properties()
    test_league_file()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL FIX-ROUND CHECKS PASSED")
