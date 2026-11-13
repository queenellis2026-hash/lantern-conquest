#!/usr/bin/env python3
"""SERV Reasoning client for Lantern Conquest — SERV Hackathon Ed. 02 entry.

Thin OpenAI-compatible client that lets the tuned player (player_v3.py)
ask SERV Reasoning for a move instead of taking its own search result.

Contract (prep §4.3, Ellis's bridge relay Nov 13, 2026):
  * POST the turn context — board, legal moves, factor breakdown — to the
    SERV inference API at https://inference-api.openserv.ai/v1.
  * Parse the returned move, validate it against the legal-move list.
  * Fall back to the local best on ANY failure: no key, timeout, HTTP
    error, unparseable reply, illegal move. The agent never holds a game
    hostage to a network call.

Configuration — environment only, never in the repo:
  SERV_API_KEY       OpenServ API key (Bearer). No key -> local only.
  SERV_BASE_URL      Default https://inference-api.openserv.ai/v1
  SERV_MODEL         Default claude-sonnet-5.5 — a model documented in the
                     SERV catalog (docs.openserv.ai changelog: $2.40 input /
                     $12.00 output per M tokens). Override when the account
                     is created; Ellis confirms the model at the credit test.
  SERV_TIMEOUT       Seconds per call. Default 30. One attempt, no retries.
  SERV_REASONING_EFFORT  Optional: passed through as `reasoning_effort`
                     when set (e.g. "low" to keep the $5 credit stretch).

The key is read from the environment at construction and is never logged,
never written to a file, and never sent anywhere except the SERV base URL
above as an Authorization Bearer header.

Usage from player_v3.py:
    from serv_reason import ServReasoner
    reasoner = ServReasoner()                       # reads env
    move, rationale, source = reasoner.choose(
        board, legal_moves, report["candidates"], me, turn,
        fallback_move=local_best)
    # source is "serv" or "local"; move is always legal.

Self-test (no key, no network — exercises parsing + fallback):
    python3 serv_reason.py --self-test

Live smoke test (needs SERV_API_KEY set; costs one call):
    SERV_API_KEY=... python3 serv_reason.py --smoke-test
"""
import json
import os
import urllib.error
import urllib.request

SIZE = 7
N = SIZE * SIZE

DEFAULT_BASE_URL = "https://inference-api.openserv.ai/v1"
DEFAULT_MODEL = "claude-sonnet-5.5"
DEFAULT_TIMEOUT = 30.0
MAX_CANDIDATES_SENT = 6  # top of the search's candidate list; keeps prompts small

SYSTEM_PROMPT = (
    "You are the move chooser for Lantern Conquest, a 7x7 stone-flipping "
    "strategy game. A move is legal only if the square is empty and "
    "orthogonally adjacent to one of your stones. Stones flip along any "
    "straight line that runs from your new stone through opponent stones "
    "to one of your stones. Corners can never be flipped once taken, so "
    "they are the strongest squares; a stone next to a still-empty corner "
    "is the only way into that corner. Answer with JSON only."
)


class ServError(Exception):
    """Anything that means SERV did not give us a usable move."""


# ------------------------------------------------------------------ parsing
def extract_json(text):
    """Pull the first JSON object out of a reply. Tolerates markdown fences
    and a sentence wrapped around the object; strict-parses the object."""
    if not isinstance(text, str):
        raise ServError("reply content is not text")
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    start = s.find("{")
    if start < 0:
        raise ServError("no JSON object in reply")
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(s[start:])
    except json.JSONDecodeError as e:
        raise ServError(f"reply JSON does not parse: {e}")
    if not isinstance(obj, dict):
        raise ServError("reply JSON is not an object")
    return obj


def parse_move(obj, legal_moves):
    """Read a move out of the parsed reply and validate it.

    Accepts {"row": r, "col": c} (0-based), {"move": [r, c]}, or
    {"move": "(r, c)"}. Returns the flat board index, or None when the
    move is missing, malformed, or not in the legal list.
    """
    legal = set(legal_moves)
    row = col = None
    if isinstance(obj.get("row"), int) and isinstance(obj.get("col"), int):
        row, col = obj["row"], obj["col"]
    elif isinstance(obj.get("move"), (list, tuple)) and len(obj["move"]) == 2:
        row, col = obj["move"]
    elif isinstance(obj.get("move"), str):
        parts = obj["move"].strip("()[] ").split(",")
        if len(parts) == 2:
            try:
                row, col = int(parts[0]), int(parts[1])
            except ValueError:
                return None
    if not (isinstance(row, int) and isinstance(col, int)):
        return None
    if not (0 <= row < SIZE and 0 <= col < SIZE):
        return None
    idx = row * SIZE + col
    return idx if idx in legal else None


def parse_rationale(obj):
    """The reply's own words for the log. Falls back to a plain sentence
    when the model forgot the field — the move still stands."""
    r = obj.get("rationale")
    if isinstance(r, str) and r.strip():
        return " ".join(r.split())
    return "SERV chose this move; no rationale was returned."


# ------------------------------------------------------------------ prompting
def build_messages(board, legal_moves, candidates, player, turn):
    """Turn context as a system prompt + one JSON user message.

    board is the flat 49-cell list (0 empty, 1 seat 0, 2 seat 1).
    candidates are player_v3's report entries (best first) with the named
    factor breakdown; only the top few are sent.
    """
    board7 = [board[r * SIZE:(r + 1) * SIZE] for r in range(SIZE)]
    legal = []
    for idx in legal_moves:
        r, c = divmod(idx, SIZE)
        legal.append({"row": r, "col": c, "display": f"({r + 1},{c + 1})"})
    cands = []
    for cand in candidates[:MAX_CANDIDATES_SENT]:
        r, c = divmod(cand["move"], SIZE)
        cands.append({
            "move": {"row": r, "col": c, "display": f"({r + 1},{c + 1})"},
            "search_value": round(cand["value"], 1),
            "flips_now": cand["flips"],
            "takes_corner": bool(cand["corner"]),
            "corner_access_after": cand["corner_access_after"],
            "mobility_after": {"mine": cand["my_mobility"],
                               "opponent": cand["opp_mobility"]},
            "opponent_best_reply_flips": cand["opp_best_reply_flips"],
            "opponent_can_take_corner": bool(cand["opp_can_take_corner"]),
            "stones_after": cand["counts_after"],
            "solved_final_diff": cand["solved_final_diff"],
        })
    context = {
        "game": "Lantern Conquest (7x7). You are seat %d, stone value %d."
                % (player, player + 1),
        "turn": turn,
        "board": board7,
        "board_key": "0 empty, 1 seat 0, 2 seat 1; rows and columns are 0-based",
        "legal_moves": legal,
        "candidates_from_local_search": cands,
        "instruction": (
            "Choose ONE move from legal_moves. Reply with JSON only, exactly "
            "this shape: {\"row\": <0-based row>, \"col\": <0-based column>, "
            "\"rationale\": \"one or two sentences naming the deciding factor "
            "and the runner-up move it beat\"}. The move must be in "
            "legal_moves; any other move is rejected and the local search "
            "result is used instead."),
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context)},
    ]


# ------------------------------------------------------------------ client
class ServReasoner:
    """One SERV Reasoning client. Safe to construct with no key: it just
    stays local-only until SERV_API_KEY exists."""

    def __init__(self, api_key=None, base_url=None, model=None, timeout=None):
        self.api_key = api_key if api_key is not None \
            else os.environ.get("SERV_API_KEY")
        self.base_url = (base_url or os.environ.get("SERV_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("SERV_MODEL") or DEFAULT_MODEL
        try:
            self.timeout = float(timeout if timeout is not None
                                 else os.environ.get("SERV_TIMEOUT")
                                 or DEFAULT_TIMEOUT)
        except ValueError:
            self.timeout = DEFAULT_TIMEOUT
        self.effort = os.environ.get("SERV_REASONING_EFFORT") or None
        self.enabled = bool(self.api_key)
        self.calls = 0
        self.serv_moves = 0
        self.fallbacks = 0

    def _post(self, messages):
        """One POST to /v1/chat/completions. Returns the assistant's text."""
        body = {
            "model": self.model,
            "messages": messages,
            # No response_format: SERV's layer rejects {"type": "json_object"}
            # (HTTP 400, verified live by Ellis Nov 13, 2026) and accepts
            # no response_format at all. extract_json pulls the object out
            # of the plain reply, so nothing is lost by leaving it off.
        }
        if self.effort:
            body["reasoning_effort"] = self.effort
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.load(e).get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001 - error body is best-effort
                pass
            raise ServError(f"HTTP {e.code} from SERV"
                            + (f": {detail}" if detail else ""))
        except Exception as e:  # noqa: BLE001 - timeout/DNS/TLS all fall back
            raise ServError(f"request failed: {e}")
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ServError("unexpected response shape from SERV")
        if not isinstance(content, str) or not content.strip():
            raise ServError("empty reply from SERV")
        return content

    def choose(self, board, legal_moves, candidates, player, turn,
               fallback_move):
        """Ask SERV for the move; return (move_index, rationale, source).

        source is "serv" when SERV's move was used, "local" whenever the
        fallback ran — including when no key is configured. The returned
        move is always in legal_moves (or the fallback, which the caller
        guarantees legal). Never raises for a SERV-side problem.
        """
        if not self.enabled:
            self.fallbacks += 1
            return (fallback_move,
                    "SERV not configured (no SERV_API_KEY); local best used.",
                    "local")
        self.calls += 1
        try:
            messages = build_messages(board, legal_moves, candidates,
                                      player, turn)
            obj = extract_json(self._post(messages))
            move = parse_move(obj, legal_moves)
            if move is None:
                raise ServError("SERV returned a move outside the legal list")
            self.serv_moves += 1
            return move, parse_rationale(obj), "serv"
        except ServError as e:
            self.fallbacks += 1
            return fallback_move, f"SERV unavailable ({e}); local best used.", "local"
        except Exception as e:  # noqa: BLE001 - any surprise also falls back
            self.fallbacks += 1
            return fallback_move, f"SERV error ({e}); local best used.", "local"


# ------------------------------------------------------------------ self-test
def _sample_position():
    """A mid-game board with a legal list, for offline checks."""
    board = [0] * N
    for i, v in [(22, 1), (23, 2), (24, 1), (29, 2), (30, 1), (31, 2),
                 (36, 1), (37, 2), (38, 1)]:
        board[i] = v
    return board


def self_test():
    """Offline checks: parsing variants, illegal-move rejection, and the
    no-key fallback. No network, no key. Returns True when all pass."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    # extract_json: fences, prose, plain object
    check("plain object",
          extract_json('{"row": 3, "col": 4}') == {"row": 3, "col": 4})
    check("fenced object",
          extract_json('```json\n{"row": 3, "col": 4}\n```') == {"row": 3, "col": 4})
    check("prose-wrapped object",
          extract_json('Here it is: {"row": 3, "col": 4} — good luck.')
          == {"row": 3, "col": 4})
    try:
        extract_json("no json here")
        check("garbage raises", False)
    except ServError:
        check("garbage raises", True)

    # parse_move: the three accepted shapes + the rejections
    legal = [15, 16, 17, 29, 36]
    check("row/col shape", parse_move({"row": 2, "col": 1}, legal) == 15)
    check("list shape", parse_move({"move": [2, 2]}, legal) == 16)
    check("string shape", parse_move({"move": "(2, 3)"}, legal) == 17)
    check("illegal square rejected", parse_move({"row": 0, "col": 0}, legal) is None)
    check("off-board rejected", parse_move({"row": 7, "col": 0}, legal) is None)
    check("missing move rejected", parse_move({"rationale": "x"}, legal) is None)

    # prompt builds and stays small
    board = _sample_position()
    cands = [{"move": 15, "value": 12.0, "flips": 2, "corner": False,
              "corner_access_after": 1, "my_mobility": 5, "opp_mobility": 4,
              "opp_best_reply_flips": 1, "opp_can_take_corner": False,
              "counts_after": [5, 4], "solved_final_diff": None}]
    msgs = build_messages(board, legal, cands, 0, 5)
    check("system message present",
          msgs[0]["role"] == "system" and len(msgs[0]["content"]) > 50)
    check("user message is JSON with legal moves",
          json.loads(msgs[1]["content"])["legal_moves"][0]["row"] == 2)

    # no-key client falls back without touching the network
    r = ServReasoner(api_key="")
    check("no key disables", r.enabled is False)
    move, rat, source = r.choose(board, legal, cands, 0, 5, fallback_move=15)
    check("no-key fallback returns local best",
          (move, source) == (15, "local") and rat.startswith("SERV not configured"))
    print("calls=%d serv=%d fallbacks=%d" % (r.calls, r.serv_moves, r.fallbacks))
    print("SELF-TEST " + ("PASSED" if ok else "FAILED"))
    return ok


def smoke_test():
    """One live call against SERV (needs SERV_API_KEY). Prints the move
    SERV returns for the sample position, or the fallback reason."""
    r = ServReasoner()
    if not r.enabled:
        print("SMOKE-TEST SKIPPED: SERV_API_KEY is not set")
        return False
    board = _sample_position()
    legal = [15, 16, 17, 29, 36]
    cands = [{"move": 15, "value": 12.0, "flips": 2, "corner": False,
              "corner_access_after": 1, "my_mobility": 5, "opp_mobility": 4,
              "opp_best_reply_flips": 1, "opp_can_take_corner": False,
              "counts_after": [5, 4], "solved_final_diff": None}]
    move, rat, source = r.choose(board, legal, cands, 0, 5, fallback_move=15)
    print(f"SMOKE-TEST source={source} move={move} rationale={rat}")
    print(f"calls={r.calls} serv={r.serv_moves} fallbacks={r.fallbacks}")
    return source == "serv"


if __name__ == "__main__":
    import sys
    if "--smoke-test" in sys.argv:
        raise SystemExit(0 if smoke_test() else 1)
    raise SystemExit(0 if self_test() else 1)
