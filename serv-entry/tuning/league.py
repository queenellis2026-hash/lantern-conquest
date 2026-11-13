#!/usr/bin/env python3
"""Self-play league: v3 (tuned) vs other SEARCH players.

Grok's review (Q4) named the biggest weakness of this build: the agent
had never been tested against a non-greedy opponent. Every scoreboard
result was against the game's 1-ply greedy sample bot. This league
fixes that gap the honest way — v3 against search players of the same
alpha-beta family at different depths and weights:

  v2-default    player_v2 with its default schedule (depths 4/5/6, solve <=12)
  v2-deep-mob10 player_v2 with the deep schedule and mobility weight 7 -> 10
  v3-shallow    player_v3 with a shallow schedule (depths 3/4/5, solve <=10)

Each matchup plays the canonical start plus seeds 10-13 from 6-ply
random prefixes, both seats (10 games per matchup), on the validated
in-process engine. Results are reported as they come out, losses
included. Honest limit, stated up front: all three opponents are the
same alpha-beta family with different parameters — a genuinely
independent engine (different author, different algorithm) was not
available, so this measures v3 against stronger and weaker search, not
against an alien style.

Usage:
    python3 league.py [--out results/league-v3-vs-search.json]
    python3 league.py --matchups v2-default --seeds 10-11  # probe
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))

# (name, brain_module, params) — params=None means the module's defaults.
OPPONENTS = {
    "v2-default": ("v2", None),
    "v2-deep-mob10": ("v2", {"depth_far": 5, "depth_mid": 6, "depth_near": 7,
                             "solve_at": 14, "w_mob": 10}),
    "v3-shallow": ("v3", {"depth_far": 3, "depth_mid": 4, "depth_near": 5,
                          "solve_at": 10}),
}


def run_matchup(opp_name, seeds, prefix_plies=6):
    mod, params = OPPONENTS[opp_name]
    brain_v3 = H.load_brain("v3", None)
    brain_opp = H.load_brain(mod, params)
    games = []
    t0 = time.time()
    specs = [("canonical", None)] + [(f"seed{s}", s) for s in seeds]
    for tag, seed in specs:
        base = E.State(E.new_board(2)) if seed is None \
            else H.prefix_state(seed, prefix_plies)
        for seat in (0, 1):
            g = H.play_game(base, brain_v3, brain_opp, seat)
            g["tag"] = tag
            games.append(g)
            print(f"  v3 vs {opp_name:>14} {tag:>10} seat{seat}: "
                  f"{g['outcome']} {g['mine']}-{g['theirs']} "
                  f"(margin {g['margin']:+d})", flush=True)
    dt = time.time() - t0
    w = sum(1 for g in games if g["outcome"] == "W")
    d = sum(1 for g in games if g["outcome"] == "D")
    l = sum(1 for g in games if g["outcome"] == "L")
    agg = sum(g["margin"] for g in games)
    summary = {"opponent": opp_name, "opponent_params": params,
               "games": len(games), "v3_wins": w, "draws": d,
               "v3_losses": l, "v3_agg_margin": agg,
               "seconds": round(dt, 1), "detail": games}
    print(f"== v3 vs {opp_name}: {w}W {d}D {l}L, aggregate margin {agg:+d}, "
          f"{dt:.1f}s ==")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matchups", default=",".join(OPPONENTS),
                    help="comma-separated opponent names")
    ap.add_argument("--seeds", default="10-13")
    ap.add_argument("--prefix-plies", type=int, default=6)
    ap.add_argument("--out", default="results/league-v3-vs-search.json")
    args = ap.parse_args()
    seeds = H.parse_seeds(args.seeds)
    t0 = time.time()
    matchups = []
    for name in args.matchups.split(","):
        name = name.strip()
        if name not in OPPONENTS:
            raise SystemExit(f"unknown opponent {name!r}; "
                             f"choose from {sorted(OPPONENTS)}")
        matchups.append(run_matchup(name, seeds, args.prefix_plies))
    total_games = sum(m["games"] for m in matchups)
    total_w = sum(m["v3_wins"] for m in matchups)
    total_d = sum(m["draws"] for m in matchups)
    total_l = sum(m["v3_losses"] for m in matchups)
    total_agg = sum(m["v3_agg_margin"] for m in matchups)
    result = {"league": "v3 vs search opponents", "seeds": args.seeds,
              "prefix_plies": args.prefix_plies,
              "games": total_games, "v3_wins": total_w, "draws": total_d,
              "v3_losses": total_l, "v3_agg_margin": total_agg,
              "seconds": round(time.time() - t0, 1), "matchups": matchups}
    print(f"== LEAGUE TOTAL: v3 {total_w}W {total_d}D {total_l}L over "
          f"{total_games} games, aggregate margin {total_agg:+d}, "
          f"{time.time() - t0:.1f}s ==")
    if args.out:
        path = os.path.join(HERE, args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
        print("wrote", path)


if __name__ == "__main__":
    main()
