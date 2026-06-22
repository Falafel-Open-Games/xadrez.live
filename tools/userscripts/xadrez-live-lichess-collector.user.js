// ==UserScript==
// @name         xadrez.live Lichess Session Collector
// @namespace    https://xadrez.live/
// @version      0.2.0
// @description  Collect Lichess puzzle and game URLs during a xadrez.live session and copy TOML blocks for session markdown.
// @author       fcz
// @match        https://lichess.org/*
// @grant        GM_setClipboard
// ==/UserScript==

(function () {
  "use strict";

  const STORAGE_KEY = "xadrez-live-lichess-collector:v1";
  const PANEL_ID = "xadrez-live-collector";

  const DEFAULT_STATE = {
    active: false,
    puzzleOfTheDayUrl: "",
    attempts: [],
    currentPuzzles: [],
    games: [],
  };

  function loadState() {
    try {
      return { ...DEFAULT_STATE, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
    } catch (_) {
      return { ...DEFAULT_STATE };
    }
  }

  function saveState(state) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function normalizePuzzleUrl(url) {
    const match = /^https:\/\/lichess\.org\/training\/([^/?#]+)/.exec(url);
    return match ? `https://lichess.org/training/${match[1]}` : "";
  }

  function normalizeGameUrl(url) {
    const match = /^https:\/\/lichess\.org\/([A-Za-z0-9]{8})(?:\/(white|black))?/.exec(url);
    if (!match) {
      return "";
    }

    return `https://lichess.org/${match[1]}${match[2] ? `/${match[2]}` : ""}`;
  }

  function quote(value) {
    return String(value || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function pushUnique(list, value) {
    if (value && !list.includes(value)) {
      list.push(value);
    }
  }

  function promptValue(label, fallback = "") {
    const value = window.prompt(label, fallback);
    return value === null ? fallback : value.trim();
  }

  function currentOpeningName() {
    const candidates = [
      document.querySelector('[data-icon=""]')?.parentElement?.textContent,
      document.querySelector(".opening")?.textContent,
      document.querySelector('[href^="/opening/"]')?.textContent,
    ];

    return candidates.find((value) => value && value.trim())?.trim() || "";
  }

  function currentOpeningUrl() {
    const link = document.querySelector('[href^="/opening/"]');
    return link ? new URL(link.getAttribute("href"), location.origin).href : "";
  }

  function finishAttempt(state) {
    if (!state.currentPuzzles.length) {
      window.alert("Nenhum puzzle na tentativa atual.");
      return;
    }

    const solved = promptValue("Quantos puzzles dessa tentativa contam como resolvidos?", String(Math.max(0, state.currentPuzzles.length - 1)));
    const note = promptValue("Nota opcional da tentativa:", "");
    state.attempts.push({
      solved,
      puzzles: [...state.currentPuzzles],
      note,
    });
    state.currentPuzzles = [];
    saveState(state);
  }

  function addCurrentPuzzle(state) {
    const url = normalizePuzzleUrl(location.href);
    if (!url) {
      window.alert("Esta URL não parece ser um puzzle do Lichess.");
      return;
    }

    pushUnique(state.currentPuzzles, url);
    saveState(state);
  }

  function setPuzzleOfTheDay(state) {
    const url = normalizePuzzleUrl(location.href);
    if (!url) {
      window.alert("Esta URL não parece ser um puzzle do Lichess.");
      return;
    }

    state.puzzleOfTheDayUrl = url;
    saveState(state);
  }

  function addCurrentGame(state) {
    const url = normalizeGameUrl(location.href);
    if (!url) {
      window.alert("Esta URL não parece ser uma partida do Lichess.");
      return;
    }

    const colorFromUrl = /\/black(?:[?#]|$)/.test(location.href)
      ? "black"
      : /\/white(?:[?#]|$)/.test(location.href)
        ? "white"
        : "";

    state.games.push({
      lichess_game_url: url,
      result: promptValue("Resultado: win, loss ou draw", ""),
      color: promptValue("Cor: white ou black", colorFromUrl),
      opening: promptValue("Abertura:", currentOpeningName()),
      opening_url: promptValue("URL da abertura:", currentOpeningUrl()),
      note: promptValue("Nota opcional da partida:", ""),
    });
    saveState(state);
  }

  function tomlArray(values) {
    return `[${values.map((value) => `"${quote(value)}"`).join(", ")}]`;
  }

  function buildToml(state) {
    const blocks = [];
    if (state.puzzleOfTheDayUrl) {
      blocks.push(`puzzle_of_the_day_url = "${quote(state.puzzleOfTheDayUrl)}"`);
    }

    const attempts = [...state.attempts];
    if (state.currentPuzzles.length) {
      attempts.push({
        solved: "",
        puzzles: [...state.currentPuzzles],
        note: "tentativa em andamento",
      });
    }

    attempts.forEach((attempt) => {
      blocks.push(`[[extra.streak_attempts]]
solved = "${quote(attempt.solved)}"
puzzles = ${tomlArray(attempt.puzzles)}
note = "${quote(attempt.note)}"`);
    });

    state.games.forEach((game) => {
      blocks.push(`[[extra.games]]
lichess_game_url = "${quote(game.lichess_game_url)}"
result = "${quote(game.result)}"
color = "${quote(game.color)}"
opening = "${quote(game.opening)}"
opening_url = "${quote(game.opening_url)}"
note = "${quote(game.note)}"`);
    });

    return blocks.join("\n\n");
  }

  function copyText(text) {
    if (!text) {
      window.alert("Nada para copiar ainda.");
      return;
    }

    if (typeof GM_setClipboard === "function") {
      GM_setClipboard(text, "text");
      window.alert("Bloco TOML copiado.");
      return;
    }

    navigator.clipboard.writeText(text).then(
      () => window.alert("Bloco TOML copiado."),
      () => window.prompt("Copie o bloco TOML:", text),
    );
  }

  function resetSession(state) {
    if (!window.confirm("Limpar o scratchpad desta sessão?")) {
      return state;
    }

    const next = { ...DEFAULT_STATE, active: true };
    saveState(next);
    return next;
  }

  function renderPanel() {
    document.getElementById(PANEL_ID)?.remove();

    const state = loadState();
    const panel = document.createElement("section");
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <style>
        #${PANEL_ID} {
          position: fixed;
          right: 16px;
          bottom: 16px;
          z-index: 99999;
          width: 310px;
          border: 1px solid #4a513f;
          border-radius: 8px;
          padding: 10px;
          background: #161912;
          color: #f2f0e7;
          box-shadow: 0 12px 36px rgba(0, 0, 0, 0.4);
          font: 13px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        #${PANEL_ID} h2 {
          margin: 0 0 8px;
          color: #d8a657;
          font-size: 13px;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        #${PANEL_ID} .xlc-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
          margin-bottom: 6px;
        }
        #${PANEL_ID} button,
        #${PANEL_ID} textarea {
          width: 100%;
          border: 1px solid #34372e;
          border-radius: 6px;
          font: inherit;
        }
        #${PANEL_ID} button {
          min-height: 34px;
          background: #242819;
          color: #f2f0e7;
          cursor: pointer;
        }
        #${PANEL_ID} button:hover {
          border-color: #d8a657;
        }
        #${PANEL_ID} textarea {
          min-height: 140px;
          margin-top: 6px;
          padding: 8px;
          background: #0f110d;
          color: #f2f0e7;
          resize: vertical;
          white-space: pre;
        }
        #${PANEL_ID} .xlc-meta {
          margin: 0 0 8px;
          color: #b8b5a8;
          font-size: 12px;
        }
      </style>
      <h2>xadrez.live</h2>
      <p class="xlc-meta">
        Tentativas: ${state.attempts.length}
        · atual: ${state.currentPuzzles.length} puzzle(s)
        · partidas: ${state.games.length}
      </p>
      <p class="xlc-meta">
        Puzzle do dia: ${state.puzzleOfTheDayUrl ? "ok" : "pendente"}
      </p>
      <div class="xlc-row">
        <button type="button" data-action="set-puzzle-of-day">Puzzle do dia</button>
        <button type="button" data-action="add-puzzle">Add puzzle</button>
      </div>
      <div class="xlc-row">
        <button type="button" data-action="finish-attempt">Fechar tentativa</button>
        <button type="button" data-action="add-game">Add partida</button>
      </div>
      <div class="xlc-row">
        <button type="button" data-action="copy">Copiar TOML</button>
        <button type="button" data-action="reset">Nova sessão</button>
      </div>
      <textarea readonly spellcheck="false">${buildToml(state)}</textarea>
    `;

    panel.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) {
        return;
      }

      let nextState = loadState();
      switch (button.dataset.action) {
        case "set-puzzle-of-day":
          setPuzzleOfTheDay(nextState);
          break;
        case "add-puzzle":
          addCurrentPuzzle(nextState);
          break;
        case "finish-attempt":
          finishAttempt(nextState);
          break;
        case "add-game":
          addCurrentGame(nextState);
          break;
        case "copy":
          copyText(buildToml(nextState));
          break;
        case "reset":
          nextState = resetSession(nextState);
          break;
      }

      renderPanel();
    });

    document.body.append(panel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderPanel, { once: true });
  } else {
    renderPanel();
  }
})();
