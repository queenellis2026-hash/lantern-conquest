#!/usr/bin/env python3
"""HTTP validation for the tuned player: two full games over the real
local API (repo/server.py), tuned player once in each seat, 0 API errors
required.

  Game S0: tuned player creates (seat 0) vs the server's built-in bot
           (botCount=1) — exactly the original proof's Game A setup.
  Game S1: a driver playing the sample bot's brain (repo/bot.py choose(),
           imported verbatim) creates as seat 0 with kind "human" (so
           bot_worker never races a seat), and the tuned player joins as
           seat 1.

Evidence is written to tuning/evidence-http/: final states, server move
logs, and the tuned player's own rationale logs.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REPO = os.path.join(ROOT, "repo")
EV = os.path.join(HERE, "evidence-http")
PORT = 8901
BASE = f"http://127.0.0.1:{PORT}"
PY = sys.executable
sys.path.insert(0, REPO)
import bot as sample_bot  # noqa: E402  (repo's own sample bot)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.load(r)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def wait_server():
    for _ in range(50):
        try:
            get("/api/games")
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise SystemExit("server did not come up")


def save_game(tag, gid):
    state = get(f"/api/games/{gid}")
    slog = get(f"/api/games/{gid}/log")
    with open(os.path.join(EV, f"{tag}-final-state.json"), "w") as f:
        json.dump(state, f, indent=2)
    with open(os.path.join(EV, f"{tag}-server-log.json"), "w") as f:
        json.dump(slog, f, indent=2)
    return state, slog


def run_tuned_player(player_file, extra, rationale_name, timeout=1200):
    cmd = [PY, os.path.join(ROOT, player_file), "--base", BASE,
           "--rationale-log", os.path.join(EV, rationale_name),
           "--poll", "0.3", "--max-seconds", "1100"] + extra
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    summary = None
    for line in p.stdout.splitlines():
        if line.startswith("{"):
            summary = json.loads(line)
    if p.returncode != 0 or summary is None:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(f"tuned player failed: {' '.join(cmd)}")
    return summary


def game_seat0(player_file):
    s = run_tuned_player(player_file,
                         ["--create", "--players", "2", "--bots", "1",
                          "--name", "Tuned"],
                         "http-seat0-rationale.log")
    state, slog = save_game("http-seat0", s["game"])
    print(f"HTTP seat0 {s['game']}: winner={s['winner']} scores={s['scores']} "
          f"moves={s['my_moves']} api_errors={s['api_errors']} "
          f"server-log entries={len(slog['log'])}")
    return s


def game_seat1(player_file):
    # driver creates as seat 0 (kind human) playing the sample bot brain
    g = post("/api/games", {"players": 2, "botCount": 0, "name": "SampleBot"})
    gid, code, token0 = g["id"], g["code"], g["yourToken"]
    proc = subprocess.Popen(
        [PY, os.path.join(ROOT, player_file), "--base", BASE,
         "--join", code, "--name", "Tuned", "--poll", "0.3",
         "--max-seconds", "1100",
         "--rationale-log", os.path.join(EV, "http-seat1-rationale.log")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 1100
        while time.time() < deadline:
            st = get(f"/api/games/{gid}")
            if st["status"] == "finished":
                break
            if st["status"] == "playing" and st["current"] == 0:
                mv = sample_bot.choose(st["board"], 0)
                if mv is not None:
                    resp = post(f"/api/games/{gid}/move",
                                {"player": 0, "token": token0,
                                 "row": mv[0], "col": mv[1]})
                    if "error" in resp:
                        raise SystemExit(f"driver move rejected: {resp}")
                time.sleep(0.1)
            else:
                time.sleep(0.2)
        else:
            raise SystemExit("seat1 game timed out")
    finally:
        out, _ = proc.communicate(timeout=120)
    summary = None
    for line in out.splitlines():
        if line.startswith("{"):
            summary = json.loads(line)
    if summary is None:
        print(out)
        raise SystemExit("tuned player (seat 1) produced no summary")
    state, slog = save_game("http-seat1", gid)
    print(f"HTTP seat1 {gid}: winner={summary['winner']} "
          f"scores={summary['scores']} moves={summary['my_moves']} "
          f"api_errors={summary['api_errors']} "
          f"server-log entries={len(slog['log'])}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default="player_v3.py")
    args = ap.parse_args()
    os.makedirs(EV, exist_ok=True)
    store = os.path.join(REPO, "games.json")
    if os.path.exists(store):
        os.remove(store)
    srv = subprocess.Popen([PY, os.path.join(REPO, "server.py"),
                            "--port", str(PORT)],
                           cwd=REPO, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        wait_server()
        print("server up on", BASE, "| validating", args.player)
        s0 = game_seat0(args.player)
        s1 = game_seat1(args.player)
        ok = (s0["api_errors"] == 0 and s1["api_errors"] == 0
              and s0["winner"] == 0 and s1["winner"] == 1)
        print("HTTP VALIDATION:", "PASS" if ok else "CHECK RESULTS",
              f"(seat0 {s0['scores']}, seat1 {s1['scores']})")
        if not ok:
            raise SystemExit(1)
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
