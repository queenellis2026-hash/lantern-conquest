#!/usr/bin/env python3
"""End-to-end test: boots the real server on a scratch port and plays full
games over real HTTP — 2-player vs server bot, 4-player bot frenzy, plus the
error paths (illegal move, wrong turn, bad token, full lobby)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import choose, legal_moves  # noqa: E402

BASE = "http://127.0.0.1:8900"


def call(path, body=None, expect=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def play_full_game(players, bot_count, label):
    status, g = call("/api/games", {"players": players, "botCount": bot_count, "name": "Tester"})
    assert status == 201, (label, status, g)
    gid = g["id"]
    tokens = {0: g["yourToken"]}
    # claim every remaining human seat so the harness can play them all
    while True:
        status, j = call(f"/api/games/{gid}/join", {"name": "Tester"})
        if status != 200:
            break
        tokens[j["yourPlayer"]] = j["yourToken"]
    moves = 0
    while True:
        status, st = call(f"/api/games/{gid}")
        assert status == 200, (label, status, st)
        if st["status"] == "finished":
            assert st["winner"] is not None, (label, "finished without winner", st)
            assert sum(st["scores"]) <= 49, (label, "too many stones", st)
            print(f"  {label}: finished in {len(st['log'])} moves, "
                  f"scores {st['scores']}, winner {st['winner']}")
            return st
        cur = st["players"][st["current"]]
        if cur["kind"] == "bot":
            time.sleep(0.05)
            continue
        mv = choose(st["board"], st["current"])
        assert mv is not None, (label, "human seat stuck with no move", st)
        status, st2 = call(f"/api/games/{gid}/move",
                           {"player": st["current"], "token": tokens[st["current"]],
                            "row": mv[0], "col": mv[1]})
        assert status == 200, (label, "move failed", status, st2)
        moves += 1
        assert moves < 200, (label, "game ran away")
        time.sleep(0.02)


def main():
    tmp = tempfile.mkdtemp()
    env = dict(os.environ)
    proc = subprocess.Popen([sys.executable, "server.py", "--port", "8900"],
                            cwd=os.path.dirname(os.path.abspath(__file__)),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(50):
            try:
                status, _ = call("/api/games")
                if status == 200:
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not come up")

        print("== full games ==")
        play_full_game(2, 1, "2p vs 1 server bot")
        play_full_game(4, 3, "4p, 3 server bots")
        play_full_game(3, 0, "3p, external bot plays all seats (via API)")

        print("== error paths ==")
        status, g = call("/api/games", {"players": 2, "botCount": 0, "name": "Tester"})
        gid = g["id"]
        # wrong token
        status, r = call(f"/api/games/{gid}/move",
                         {"player": 0, "token": "nope", "row": 0, "col": 1})
        assert status == 403, ("bad token should 403", status, r)
        # occupied cell
        status, r = call(f"/api/games/{gid}/move",
                         {"player": 0, "token": g["yourToken"], "row": 0, "col": 0})
        assert status == 400, ("occupied cell should 400", status, r)
        # non-adjacent cell
        status, r = call(f"/api/games/{gid}/move",
                         {"player": 0, "token": g["yourToken"], "row": 3, "col": 3})
        assert status == 400, ("non-adjacent should 400", status, r)
        # wrong turn: player 1 has no token yet, so join first, then move out of turn
        status, j = call(f"/api/games/{gid}/join", {"name": "P2"})
        assert status == 200, ("join failed", status, j)
        status, r = call(f"/api/games/{gid}/move",
                         {"player": 1, "token": j["yourToken"], "row": 6, "col": 6})
        assert status == 400, ("out-of-turn should 400", status, r)
        # join a full game
        status, r = call(f"/api/games/{gid}/join", {"name": "P3"})
        assert status == 409, ("full lobby should 409", status, r)
        # legal move works and flips are counted
        status, r = call(f"/api/games/{gid}/move",
                         {"player": 0, "token": g["yourToken"], "row": 0, "col": 1})
        assert status == 200 and r["board"][0][1] == 1, ("legal move failed", status, r)
        # docs + lobby list
        status, r = call("/api/docs")
        assert status == 200 and r["name"] == "Lantern Conquest", ("docs broken", status)
        status, r = call("/api/games")
        assert status == 200 and len(r["games"]) >= 4, ("lobby list broken", status, r)
        print("  all error paths behave")
        print("ALL TESTS PASSED")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
