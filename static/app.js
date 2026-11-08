/* Lantern Conquest — browser client. No build step, no login.
   State lives in localStorage (your seat token for this game). */
const SIZE = 7;
const ORTHO = [[-1, 0], [1, 0], [0, -1], [0, 1]];
const DIRS = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];

let state = null;          // latest server state
let myPlayer = null, myToken = null, myGameId = null;
let replayIdx = null;      // null = live; else index into log (entries applied)

const $ = id => document.getElementById(id);

function api(path, opts) {
  return fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}))
    .then(r => r.json().then(j => ({ ok: r.ok, status: r.status, body: j })));
}

function legalMoves(board, p) {
  const me = p + 1, out = [];
  for (let r = 0; r < SIZE; r++) for (let c = 0; c < SIZE; c++) {
    if (board[r][c] !== 0) continue;
    for (const [dr, dc] of ORTHO) {
      const nr = r + dr, nc = c + dc;
      if (nr >= 0 && nr < SIZE && nc >= 0 && nc < SIZE && board[nr][nc] === me) { out.push([r, c]); break; }
    }
  }
  return out;
}

function flipsFor(board, p, r, c) {
  const me = p + 1, out = [];
  for (const [dr, dc] of DIRS) {
    const line = [];
    let nr = r + dr, nc = c + dc;
    while (nr >= 0 && nr < SIZE && nc >= 0 && nc < SIZE) {
      const v = board[nr][nc];
      if (v === 0) break;
      if (v === me) { out.push(...line); break; }
      line.push([nr, nc]);
      nr += dr; nc += dc;
    }
  }
  return out;
}

/* ---------- lobby ---------- */
async function refreshLobby() {
  const res = await api("api/games");
  const el = $("openGames");
  if (!res.ok || !res.body.games || !res.body.games.length) {
    el.innerHTML = "<em>No open games right now — create one.</em>";
    return;
  }
  el.innerHTML = res.body.games.map(g =>
    `<span class="g" data-id="${g.id}">${g.code} · ${g.players}p · ${g.status} · ${g.seated} seated — click to join</span>`).join("");
  el.querySelectorAll(".g").forEach(n => n.onclick = () => joinGame(n.dataset.id));
}

$("createBtn").onclick = async () => {
  const name = $("myName").value.trim() || "Player 1";
  const players = parseInt($("numPlayers").value, 10);
  const botCount = parseInt($("botCount").value, 10);
  const res = await api("api/games", { method: "POST", body: JSON.stringify({ players, botCount, name }) });
  if (!res.ok) { $("lobbyMsg").textContent = "Could not create game: " + (res.body.error || res.status); return; }
  enterGame(res.body);
};

$("joinBtn").onclick = () => {
  const code = $("joinCode").value.trim();
  if (code) joinGame(code);
};

async function joinGame(idOrCode) {
  const name = $("myName").value.trim() || "Player 1";
  const res = await api(`api/games/${encodeURIComponent(idOrCode)}/join`, { method: "POST", body: JSON.stringify({ name }) });
  if (!res.ok) { $("lobbyMsg").textContent = "Could not join: " + (res.body.error || res.status); return; }
  enterGame(res.body);
}

function enterGame(g) {
  myGameId = g.id; myPlayer = g.yourPlayer; myToken = g.yourToken;
  localStorage.setItem("lc", JSON.stringify({ id: g.id, player: myPlayer, token: myToken }));
  state = g; replayIdx = null;
  $("lobby").classList.add("hidden");
  $("game").classList.remove("hidden");
  $("gameCode").textContent = g.code;
  render();
}

$("leaveBtn").onclick = () => {
  localStorage.removeItem("lc");
  myGameId = null; state = null;
  $("game").classList.add("hidden");
  $("lobby").classList.remove("hidden");
  refreshLobby();
};

/* ---------- game view ---------- */
function render() {
  if (!state) return;
  const board = replayBoard();
  const status = state.status;
  const me = state.players[myPlayer];
  let statusText;
  if (status === "lobby") statusText = "Waiting for players…";
  else if (status === "finished") {
    statusText = state.winner === "draw" ? "Draw!" :
      `🏆 ${state.players[state.winner].name} wins with ${state.scores[state.winner]} stones!`;
  } else {
    const cur = state.players[state.current];
    statusText = state.current === myPlayer ? "Your turn — place a stone on a glowing cell."
      : `${cur.name}'s turn…`;
  }
  $("statusLine").textContent = statusText;

  $("players").innerHTML = state.players.map((p, i) => `
    <div class="pcard ${status === "playing" && state.current === i ? "active" : ""}">
      <span class="dot" style="background:${p.color}"></span><b>${p.name}</b>
      ${i === myPlayer ? " (you)" : ""} ${p.kind === "bot" ? "🤖" : ""}
      <div class="score">${state.scores[i]}</div>
      <div class="meta">${p.eliminated ? "eliminated" : (status === "playing" && state.current === i ? "to move" : "")}</div>
    </div>`).join("");

  const live = replayIdx === null;
  const legals = (live && status === "playing" && state.current === myPlayer)
    ? legalMoves(state.board, myPlayer).map(m => m.join(",")) : [];
  const last = state.lastMove;
  const b = $("board");
  b.innerHTML = "";
  for (let r = 0; r < SIZE; r++) for (let c = 0; c < SIZE; c++) {
    const cell = document.createElement("button");
    cell.className = "cell";
    const v = board[r][c];
    if (v) cell.innerHTML = `<span class="stone" style="background:${state.players[v - 1].color}"></span>`;
    if (legals.includes(r + "," + c)) cell.classList.add("legal");
    if (last && last.row === r && last.col === c && live) cell.classList.add("last");
    if (!live) cell.classList.add("replay-dim");
    cell.onclick = () => onCell(r, c);
    b.appendChild(cell);
  }

  $("log").innerHTML = state.log.map((e, i) => {
    const p = state.players[e.player];
    return `<li><b style="color:${p.color}">${p.name}</b> → (${e.row + 1},${e.col + 1})` +
      (e.flipped.length ? ` flipped ${e.flipped.length}` : " no flip") +
      ` — ${e.scores.join("–")}</li>`;
  }).join("") || "<li><em>No moves yet.</em></li>";
  const logEl = $("log");
  logEl.scrollTop = logEl.scrollHeight;

  $("replayLabel").textContent = live ? `live · turn ${state.turn}` :
    `replay ${replayIdx}/${state.log.length}`;
}

function replayBoard() {
  if (replayIdx === null) return state.board;
  // rebuild from the initial corners + first replayIdx log entries
  const board = Array.from({ length: SIZE }, () => Array(SIZE).fill(0));
  const starts = [[0, 0], [SIZE - 1, SIZE - 1], [0, SIZE - 1], [SIZE - 1, 0]];
  state.players.forEach((p, i) => { const [r, c] = starts[i]; board[r][c] = i + 1; });
  for (let i = 0; i < replayIdx; i++) {
    const e = state.log[i];
    const flipped = flipsFor(board, e.player, e.row, e.col);
    board[e.row][e.col] = e.player + 1;
    flipped.forEach(([fr, fc]) => board[fr][fc] = e.player + 1);
  }
  return board;
}

async function onCell(r, c) {
  if (!state || state.status !== "playing" || state.current !== myPlayer || replayIdx !== null) return;
  const res = await api(`api/games/${myGameId}/move`, {
    method: "POST",
    body: JSON.stringify({ player: myPlayer, token: myToken, row: r, col: c }),
  });
  if (!res.ok) { $("gameMsg").textContent = res.body.error || "Move rejected."; return; }
  $("gameMsg").textContent = "";
  state = res.body;
  render();
}

$("replayPrev").onclick = () => {
  if (!state) return;
  if (replayIdx === null) replayIdx = state.log.length;
  replayIdx = Math.max(0, replayIdx - 1);
  render();
};
$("replayNext").onclick = () => {
  if (!state || replayIdx === null) return;
  replayIdx = Math.min(state.log.length, replayIdx + 1);
  if (replayIdx === state.log.length) replayIdx = null;
  render();
};
$("replayLive").onclick = () => { replayIdx = null; render(); };

/* ---------- polling ---------- */
setInterval(async () => {
  if (myGameId) {
    const res = await api(`api/games/${myGameId}`);
    if (res.ok) { state = res.body; render(); }
  } else {
    refreshLobby();
  }
}, 2000);

// resume a game if the browser remembers one
(function init() {
  try {
    const saved = JSON.parse(localStorage.getItem("lc") || "null");
    if (saved && saved.id) {
      api(`api/games/${saved.id}`).then(res => {
        if (res.ok && res.body.status !== "finished") {
          myGameId = saved.id; myPlayer = saved.player; myToken = saved.token;
          state = res.body;
          $("lobby").classList.add("hidden");
          $("game").classList.remove("hidden");
          $("gameCode").textContent = state.code;
          render();
        }
      });
    }
  } catch (e) { /* fresh start */ }
  refreshLobby();
})();
