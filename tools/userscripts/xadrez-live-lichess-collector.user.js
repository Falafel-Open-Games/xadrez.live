// ==UserScript==
// @name         xadrez.live Session Collector
// @namespace    https://xadrez.live/
// @version      0.13.0
// @description  Collect chess puzzle, game, notes, and Restream chat usernames during a xadrez.live session.
// @author       fcz
// @match        https://lichess.org/*
// @match        https://www.chess.com/*
// @match        https://app.restream.io/*
// @match        https://chat.restream.io/*
// @grant        GM_getValue
// @grant        GM_setClipboard
// @grant        GM_setValue
// ==/UserScript==

(function () {
  "use strict";

  const STORAGE_KEY = "xadrez-live-lichess-collector:v1";
  const PANEL_ID = "xadrez-live-collector";
  const SELF_SUPPORTERS = {
    YouTube: new Set(["fczuardi"]),
    Twitch: new Set(["sedentarismo"]),
  };

  const DEFAULT_STATE = {
    active: false,
    collapsed: false,
    puzzleOfTheDayUrl: "",
    duration: "",
    rapid: "",
    puzzles: "",
    descriptionNotes: "",
    attempts: [],
    currentPuzzles: [],
    games: [],
    supporters: [],
  };

  function loadState() {
    if (typeof GM_getValue === "function") {
      try {
        const stored = GM_getValue(STORAGE_KEY, "");
        if (stored) {
          return { ...DEFAULT_STATE, ...JSON.parse(stored) };
        }
      } catch (_) {
        return { ...DEFAULT_STATE };
      }
    }

    try {
      const state = { ...DEFAULT_STATE, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
      if (typeof GM_setValue === "function") {
        GM_setValue(STORAGE_KEY, JSON.stringify(state));
      }
      return state;
    } catch (_) {
      return { ...DEFAULT_STATE };
    }
  }

  function saveState(state) {
    const serialized = JSON.stringify(state);
    if (typeof GM_setValue === "function") {
      GM_setValue(STORAGE_KEY, serialized);
    }
    localStorage.setItem(STORAGE_KEY, serialized);
  }

  function normalizePuzzleUrl(url) {
    const match = /^https:\/\/lichess\.org\/training\/(?:mix\/)?([^/?#]+)/.exec(url);
    return match ? `https://lichess.org/training/${match[1]}` : "";
  }

  function currentPuzzleSessionUrls() {
    const links = [...document.querySelectorAll(".puzzle__session a[href]")];
    const urls = links
      .map((link) => normalizePuzzleUrl(new URL(link.getAttribute("href"), location.origin).href))
      .filter(Boolean);

    return [...new Set(urls)];
  }

  function currentPuzzleUrl() {
    const revealedLink = document.querySelector('.infos.puzzle a[href^="/training/"]');
    if (revealedLink) {
      return normalizePuzzleUrl(new URL(revealedLink.getAttribute("href"), location.origin).href);
    }

    return normalizePuzzleUrl(location.href);
  }

  function normalizeLichessGameUrl(url) {
    const match = /^https:\/\/lichess\.org\/([A-Za-z0-9]{8})(?:\/(white|black))?/.exec(url);
    if (!match) {
      return "";
    }

    return `https://lichess.org/${match[1]}${match[2] ? `/${match[2]}` : ""}`;
  }

  function normalizeChessComGameUrl(url) {
    const match = /^https:\/\/www\.chess\.com\/(?:analysis\/)?game\/live\/(\d+)/.exec(url);
    return match ? `https://www.chess.com/analysis/game/live/${match[1]}` : "";
  }

  function currentGameContext() {
    const lichessUrl = normalizeLichessGameUrl(location.href);
    if (lichessUrl) {
      return {
        platform: "lichess",
        gameUrl: lichessUrl,
        colorFromUrl: /\/black(?:[?#]|$)/.test(location.href)
          ? "black"
          : /\/white(?:[?#]|$)/.test(location.href)
            ? "white"
            : "",
      };
    }

    const chessComUrl = normalizeChessComGameUrl(location.href);
    if (chessComUrl) {
      return {
        platform: "chess.com",
        gameUrl: chessComUrl,
        colorFromUrl: "",
      };
    }

    return null;
  }

  function quote(value) {
    return String(value || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function multilineQuote(value) {
    return String(value || "")
      .replace(/\r\n?/g, "\n")
      .replace(/\\/g, "\\\\")
      .replace(/"""/g, '\\"\\"\\"');
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
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

  function selectValue(label, options, fallback = "") {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.innerHTML = `
        <style>
          .xlc-select-overlay {
            position: fixed;
            inset: 0;
            z-index: 100000;
            display: grid;
            place-items: center;
            background: rgba(0, 0, 0, 0.35);
            font: 14px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          .xlc-select-dialog {
            width: min(320px, calc(100vw - 32px));
            border: 1px solid #4a513f;
            border-radius: 8px;
            padding: 14px;
            background: #161912;
            color: #f2f0e7;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
          }
          .xlc-select-dialog label {
            display: grid;
            gap: 8px;
            color: #d8a657;
            font-weight: 700;
          }
          .xlc-select-dialog select {
            min-height: 36px;
            border: 1px solid #34372e;
            border-radius: 6px;
            padding: 0 8px;
            background: #0f110d;
            color: #f2f0e7;
            font: inherit;
          }
          .xlc-select-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-top: 12px;
          }
          .xlc-select-actions button {
            min-height: 34px;
            border: 1px solid #34372e;
            border-radius: 6px;
            background: #242819;
            color: #f2f0e7;
            font: inherit;
            cursor: pointer;
          }
          .xlc-select-actions button:hover {
            border-color: #d8a657;
          }
        </style>
        <div class="xlc-select-overlay">
          <form class="xlc-select-dialog">
            <label>
              ${label}
              <select name="value">
                ${options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("")}
              </select>
            </label>
            <div class="xlc-select-actions">
              <button type="submit">Use value</button>
              <button type="button" data-action="cancel">Cancel</button>
            </div>
          </form>
        </div>
      `;

      const form = overlay.querySelector("form");
      const select = overlay.querySelector("select");
      select.value = fallback;
      if (select.value !== fallback) {
        select.value = "";
      }

      function close(value) {
        overlay.remove();
        resolve(value);
      }

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        close(select.value);
      });
      form.querySelector('[data-action="cancel"]').addEventListener("click", () => close(fallback));
      document.body.append(overlay);
      select.focus();
    });
  }

  function postStatsValue(state, key) {
    return String(state[key] || "").trim();
  }

  function postStatsDialog(state) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.innerHTML = `
        <style>
          .xlc-stats-overlay {
            position: fixed;
            inset: 0;
            z-index: 100000;
            display: grid;
            place-items: center;
            background: rgba(0, 0, 0, 0.35);
            font: 14px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          .xlc-stats-dialog {
            width: min(360px, calc(100vw - 32px));
            border: 1px solid #4a513f;
            border-radius: 8px;
            padding: 14px;
            background: #161912;
            color: #f2f0e7;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
          }
          .xlc-stats-dialog label {
            display: grid;
            gap: 6px;
            margin-bottom: 10px;
            color: #d8a657;
            font-weight: 700;
          }
          .xlc-stats-dialog input {
            min-height: 36px;
            border: 1px solid #34372e;
            border-radius: 6px;
            padding: 0 8px;
            background: #0f110d;
            color: #f2f0e7;
            font: inherit;
          }
          .xlc-stats-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-top: 12px;
          }
          .xlc-stats-actions button {
            min-height: 34px;
            border: 1px solid #34372e;
            border-radius: 6px;
            background: #242819;
            color: #f2f0e7;
            font: inherit;
            cursor: pointer;
          }
          .xlc-stats-actions button:hover {
            border-color: #d8a657;
          }
        </style>
        <div class="xlc-stats-overlay">
          <form class="xlc-stats-dialog">
            <label>
              Duration
              <input name="duration" autocomplete="off" value="${escapeHtml(postStatsValue(state, "duration"))}">
            </label>
            <label>
              Rapid
              <input name="rapid" autocomplete="off" value="${escapeHtml(postStatsValue(state, "rapid"))}">
            </label>
            <label>
              Puzzles
              <input name="puzzles" autocomplete="off" value="${escapeHtml(postStatsValue(state, "puzzles"))}">
            </label>
            <div class="xlc-stats-actions">
              <button type="submit">Save stats</button>
              <button type="button" data-action="cancel">Cancel</button>
            </div>
          </form>
        </div>
      `;

      const form = overlay.querySelector("form");

      function close(value) {
        overlay.remove();
        resolve(value);
      }

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const data = new FormData(form);
        close({
          duration: String(data.get("duration") || "").trim(),
          rapid: String(data.get("rapid") || "").trim(),
          puzzles: String(data.get("puzzles") || "").trim(),
        });
      });
      form.querySelector('[data-action="cancel"]').addEventListener("click", () => close(null));
      document.body.append(overlay);
      form.elements.duration.focus();
    });
  }

  async function setPostStats(state) {
    const values = await postStatsDialog(state);
    if (!values) {
      return;
    }

    state.duration = values.duration;
    state.rapid = values.rapid;
    state.puzzles = values.puzzles;
    saveState(state);
  }

  function sessionNotesDialog(state) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.innerHTML = `
        <style>
          .xlc-notes-overlay {
            position: fixed;
            inset: 0;
            z-index: 100000;
            display: grid;
            place-items: center;
            background: rgba(0, 0, 0, 0.35);
            font: 14px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          .xlc-notes-dialog {
            width: min(460px, calc(100vw - 32px));
            border: 1px solid #4a513f;
            border-radius: 8px;
            padding: 14px;
            background: #161912;
            color: #f2f0e7;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
          }
          .xlc-notes-dialog label {
            display: grid;
            gap: 6px;
            color: #d8a657;
            font-weight: 700;
          }
          .xlc-notes-dialog textarea {
            min-height: 180px;
            border: 1px solid #34372e;
            border-radius: 6px;
            padding: 8px;
            background: #0f110d;
            color: #f2f0e7;
            font: inherit;
            resize: vertical;
          }
          .xlc-notes-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-top: 12px;
          }
          .xlc-notes-actions button {
            min-height: 34px;
            border: 1px solid #34372e;
            border-radius: 6px;
            background: #242819;
            color: #f2f0e7;
            font: inherit;
            cursor: pointer;
          }
          .xlc-notes-actions button:hover {
            border-color: #d8a657;
          }
        </style>
        <div class="xlc-notes-overlay">
          <form class="xlc-notes-dialog">
            <label>
              Description notes
              <textarea name="descriptionNotes" spellcheck="true">${escapeHtml(state.descriptionNotes)}</textarea>
            </label>
            <div class="xlc-notes-actions">
              <button type="submit">Save notes</button>
              <button type="button" data-action="cancel">Cancel</button>
            </div>
          </form>
        </div>
      `;

      const form = overlay.querySelector("form");

      function close(value) {
        overlay.remove();
        resolve(value);
      }

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const data = new FormData(form);
        close(String(data.get("descriptionNotes") || "").trim());
      });
      form.querySelector('[data-action="cancel"]').addEventListener("click", () => close(null));
      document.body.append(overlay);
      form.elements.descriptionNotes.focus();
    });
  }

  async function setDescriptionNotes(state) {
    const notes = await sessionNotesDialog(state);
    if (notes === null) {
      return;
    }

    state.descriptionNotes = notes;
    saveState(state);
  }

  function firstOpeningLink(selectors) {
    return selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  }

  function openingLink() {
    return firstOpeningLink([
      '.explorer-box .title a[href^="/opening/"]',
      '.explorer-box .title a[href^="https://lichess.org/opening/"]',
      '.analyse__tools a[href^="/opening/"]',
      '.analyse__tools a[href^="https://lichess.org/opening/"]',
      'a[href^="/opening/"]',
      'a[href^="https://lichess.org/opening/"]',
    ]);
  }

  function cleanOpeningName(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .replace(/^[A-E]\d{2}\s+/, "")
      .trim();
  }

  function currentOpeningName() {
    const link = openingLink();
    const candidates = [
      link?.getAttribute("title"),
      link?.textContent,
      document.querySelector(".opening")?.textContent,
      document.querySelector('[data-icon=""]')?.parentElement?.textContent,
    ];

    return candidates.map(cleanOpeningName).find(Boolean) || "";
  }

  function currentOpeningUrl() {
    const link = openingLink();
    const href = link?.getAttribute("href") || link?.href || "";
    return href ? new URL(href, location.origin).href : "";
  }

  function finishAttempt(state) {
    if (!state.currentPuzzles.length) {
      window.alert("No puzzles in the current attempt.");
      return;
    }

    const solved = promptValue("How many puzzles count as solved in this attempt?", String(Math.max(0, state.currentPuzzles.length - 1)));
    const note = promptValue("Optional attempt note:", "");
    state.attempts.push({
      solved,
      puzzles: [...state.currentPuzzles],
      note,
    });
    state.currentPuzzles = [];
    saveState(state);
  }

  function addCurrentPuzzle(state) {
    const url = currentPuzzleUrl();
    if (!url) {
      window.alert("Could not find a revealed puzzle link or a Lichess puzzle URL.");
      return;
    }

    pushUnique(state.currentPuzzles, url);
    saveState(state);
  }

  function syncCurrentPuzzleSession(state) {
    const urls = currentPuzzleSessionUrls();
    if (!urls.length) {
      window.alert("Could not find puzzle streak links in .puzzle__session.");
      return;
    }

    state.currentPuzzles = urls;
    saveState(state);
  }

  function setPuzzleOfTheDay(state) {
    const url = currentPuzzleUrl();
    if (!url) {
      window.alert("Could not find a revealed puzzle link or a Lichess puzzle URL.");
      return;
    }

    state.puzzleOfTheDayUrl = url;
    saveState(state);
  }

  async function addCurrentGame(state) {
    const context = currentGameContext();
    if (!context) {
      window.alert("This URL does not look like a supported Lichess or Chess.com game.");
      return;
    }

    const existingGameIndex = state.games.findIndex((game) => {
      const gameUrl = game.game_url || game.lichess_game_url || "";
      return gameUrl === context.gameUrl;
    });
    const existingGame = existingGameIndex === -1 ? {} : state.games[existingGameIndex];
    const game = {
      platform: context.platform,
      game_url: context.gameUrl,
      result: await selectValue(
        "Result",
        [
          { value: "", label: "Not set" },
          { value: "win", label: "win" },
          { value: "loss", label: "loss" },
          { value: "draw", label: "draw" },
        ],
        existingGame.result || "",
      ),
      color: await selectValue(
        "Color",
        [
          { value: "", label: "Not set" },
          { value: "white", label: "white" },
          { value: "black", label: "black" },
        ],
        existingGame.color || context.colorFromUrl,
      ),
      note: promptValue("Optional game note:", existingGame.note || ""),
    };

    if (context.platform === "lichess") {
      game.opening = promptValue("Opening:", existingGame.opening || currentOpeningName());
      game.opening_url = promptValue("Opening URL:", existingGame.opening_url || currentOpeningUrl());
    }

    if (existingGameIndex === -1) {
      state.games.push(game);
    } else {
      state.games[existingGameIndex] = game;
    }
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

    if (state.duration || state.rapid || state.puzzles) {
      blocks.push(`duration = "${quote(state.duration)}"
rapid = "${quote(state.rapid)}"
puzzles = "${quote(state.puzzles)}"`);
    }

    if (state.descriptionNotes) {
      blocks.push(`description_notes = """${multilineQuote(state.descriptionNotes)}"""`);
    }

    const attempts = [...state.attempts];
    if (state.currentPuzzles.length) {
      attempts.push({
        solved: "",
        puzzles: [...state.currentPuzzles],
        note: "attempt in progress",
      });
    }

    attempts.forEach((attempt) => {
      blocks.push(`[[extra.streak_attempts]]
solved = "${quote(attempt.solved)}"
puzzles = ${tomlArray(attempt.puzzles)}
note = "${quote(attempt.note)}"`);
    });

    state.games.forEach((game) => {
      const lines = ["[[extra.games]]"];
      if (game.platform) {
        lines.push(`platform = "${quote(game.platform)}"`);
      }
      if (game.game_url) {
        lines.push(`game_url = "${quote(game.game_url)}"`);
      } else if (game.lichess_game_url) {
        lines.push(`lichess_game_url = "${quote(game.lichess_game_url)}"`);
      }
      lines.push(`result = "${quote(game.result)}"`);
      lines.push(`color = "${quote(game.color)}"`);
      if (game.opening) {
        lines.push(`opening = "${quote(game.opening)}"`);
      }
      if (game.opening_url) {
        lines.push(`opening_url = "${quote(game.opening_url)}"`);
      }
      lines.push(`note = "${quote(game.note)}"`);
      blocks.push(lines.join("\n"));
    });

    (state.supporters || []).forEach((supporter) => {
      const lines = ["[[extra.supporters]]"];
      lines.push(`platform = "${quote(supporter.platform)}"`);
      lines.push(`name = "${quote(supporter.name)}"`);
      if (supporter.url) {
        lines.push(`url = "${quote(supporter.url)}"`);
      }
      blocks.push(lines.join("\n"));
    });

    return blocks.join("\n\n");
  }

  function copyText(text) {
    if (!text) {
      window.alert("Nothing to copy yet.");
      return;
    }

    const panelTextarea = document.querySelector(`#${PANEL_ID} textarea`);
    if (panelTextarea) {
      panelTextarea.value = text;
      panelTextarea.focus();
      panelTextarea.select();
    }

    if (typeof GM_setClipboard === "function") {
      try {
        GM_setClipboard(text, "text");
        window.alert("Copied.");
        return;
      } catch (_) {
        // Fall through to the browser clipboard and prompt fallback below.
      }
    }

    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(
        () => window.alert("Copied."),
        () => window.prompt("Copy this text:", text),
      );
      return;
    }

    window.prompt("Copy this text:", text);
  }

  function isRestreamPage() {
    return location.hostname === "app.restream.io" || location.hostname === "chat.restream.io";
  }

  function restreamPlatformFromSrc(src) {
    const value = String(src || "");
    if (/youtube/i.test(value) || value.includes("platform-5-social.png")) {
      return "YouTube";
    }
    if (/twitch/i.test(value) || value.includes("platform-1.png")) {
      return "Twitch";
    }
    return "";
  }

  function queryAll(root, selector) {
    try {
      return [...root.querySelectorAll(selector)];
    } catch (_) {
      return [];
    }
  }

  function cleanRestreamAuthor(value) {
    const author = String(value || "")
      .replace(/[\u200b-\u200d\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim();

    if (
      !author ||
      author.length > 80 ||
      /[\n\r]/.test(author) ||
      /^(Restream|Restream\.io|YouTube|Twitch|Chat)$/i.test(author) ||
      /^(Today|Yesterday|just now)$/i.test(author)
    ) {
      return "";
    }

    return author.startsWith("@") ? author : `@${author}`;
  }

  function cleanRestreamMessageAuthor(value, platform) {
    const author = String(value || "")
      .replace(/[\u200b-\u200d\ufeff]/g, "")
      .replace(/\s+/g, " ")
      .trim();

    if (!author || author.length > 80 || /[\n\r]/.test(author)) {
      return "";
    }
    if (/^(YouTube|Twitch|Chat)$/i.test(author) || /^(Today|Yesterday|just now)$/i.test(author)) {
      return "";
    }
    if (/^Restream(?:\.io)?$/i.test(author)) {
      return "Host";
    }
    if ((platform === "YouTube" || platform === "Twitch") && !author.startsWith("@")) {
      return `@${author}`;
    }
    return author;
  }

  function authorFromProfileHref(href) {
    const value = String(href || "");
    const youtube = /youtube\.com\/@([^/?#]+)/i.exec(value);
    if (youtube) {
      return cleanRestreamAuthor(`@${decodeURIComponent(youtube[1])}`);
    }

    const twitch = /twitch\.tv\/([^/?#]+)/i.exec(value);
    if (twitch) {
      return cleanRestreamAuthor(`@${decodeURIComponent(twitch[1])}`);
    }

    return "";
  }

  function restreamCardPlatform(card) {
    const platforms = queryAll(
      card,
      'img[src*="restream.io/img/api/platforms/platform-"], img.icon-platform, img[alt], [aria-label], [title]',
    )
      .map((element) =>
        restreamPlatformFromSrc(
          [
            element.getAttribute("src"),
            element.getAttribute("alt"),
            element.getAttribute("aria-label"),
            element.getAttribute("title"),
          ].join(" "),
        ),
      )
      .filter(Boolean);

    return [...new Set(platforms)][0] || "Chat";
  }

  function restreamAuthorFromCard(card) {
    const profileAuthor = queryAll(card, 'a[href*="youtube.com/@"], a[href*="twitch.tv/"]')
      .map((link) => authorFromProfileHref(link.getAttribute("href")))
      .find(Boolean);
    if (profileAuthor) {
      return profileAuthor;
    }

    const author = queryAll(
      card,
      [
        ".MuiTypography-subtitle2",
        '[data-testid*="author" i]',
        '[data-testid*="sender" i]',
        '[data-testid*="username" i]',
        '[class*="author" i]',
        '[class*="sender" i]',
        '[class*="username" i]',
        '[class*="user-name" i]',
        '[class*="display-name" i]',
      ].join(", "),
    )
      .map((element) => cleanRestreamAuthor(element.textContent))
      .find(Boolean);

    return author || "";
  }

  function restreamRawAuthorFromCard(card, platform) {
    const profileAuthor = queryAll(card, 'a[href*="youtube.com/@"], a[href*="twitch.tv/"]')
      .map((link) => authorFromProfileHref(link.getAttribute("href")))
      .find(Boolean);
    if (profileAuthor) {
      return profileAuthor;
    }

    return queryAll(
      card,
      [
        ".MuiTypography-subtitle2",
        '[data-testid*="author" i]',
        '[data-testid*="sender" i]',
        '[data-testid*="username" i]',
        '[class*="author" i]',
        '[class*="sender" i]',
        '[class*="username" i]',
        '[class*="user-name" i]',
        '[class*="display-name" i]',
      ].join(", "),
    )
      .map((element) => cleanRestreamMessageAuthor(element.textContent, platform))
      .find(Boolean) || "";
  }

  function restreamClockFromCard(card) {
    const value = queryAll(card, ".MuiTypography-caption, time, [datetime], [class*='time' i], [class*='timestamp' i]")
      .map((element) => element.getAttribute("datetime") || element.textContent)
      .map((text) => String(text || "").trim())
      .find((text) => /^\d{1,2}:\d{2}:\d{2}$/.test(text));
    return value || "";
  }

  function restreamTextFromCard(card) {
    const value = queryAll(card, ".chat-text-normal, [data-testid*='message' i], [class*='message-text' i], [class*='text' i]")
      .map((element) => String(element.textContent || "").replace(/\s+/g, " ").trim())
      .find(Boolean);
    return value || "";
  }

  function restreamAuthorFromEmbedMessage(message) {
    const author = queryAll(
      message,
      [
        ".message-sender",
        '[data-testid*="author" i]',
        '[data-testid*="sender" i]',
        '[data-testid*="username" i]',
        '[class*="author" i]',
        '[class*="sender" i]',
        '[class*="username" i]',
      ].join(", "),
    )
      .map((element) => cleanRestreamAuthor(element.textContent))
      .find(Boolean);

    return author || "";
  }

  function restreamSupporterUrl(platform, name) {
    const handle = name.replace(/^@/, "");
    if (!handle) {
      return "";
    }
    if (platform === "YouTube") {
      return `https://www.youtube.com/@${encodeURIComponent(handle)}`;
    }
    if (platform === "Twitch") {
      return `https://www.twitch.tv/${encodeURIComponent(handle)}`;
    }
    return "";
  }

  function normalizedSupporterHandle(name) {
    return String(name || "")
      .replace(/^@/, "")
      .trim()
      .toLowerCase();
  }

  function isSelfSupporter(platform, name) {
    return SELF_SUPPORTERS[platform]?.has(normalizedSupporterHandle(name)) || false;
  }

  function restreamSupporters() {
    const byKey = new Map();
    const cards = queryAll(
      document,
      [
        '[id^="message-card-studio-"]',
        '[data-testid*="message" i]',
        '[class*="message-card" i]',
        '[class*="chat-message" i]',
        '[role="listitem"]',
      ].join(", "),
    );

    cards.forEach((card) => {
      const name = restreamAuthorFromCard(card);
      if (!name) {
        return;
      }

      const platform = restreamCardPlatform(card);
      if (isSelfSupporter(platform, name)) {
        return;
      }

      const key = `${platform}\0${name}`;
      if (!byKey.has(key)) {
        byKey.set(key, { platform, name });
      }
    });

    const embedMessages = queryAll(document, ".chat-messages .message-item, .message-item");
    embedMessages.forEach((message) => {
      const name = restreamAuthorFromEmbedMessage(message);
      if (!name) {
        return;
      }

      const platform = restreamCardPlatform(message);
      if (isSelfSupporter(platform, name)) {
        return;
      }

      const key = `${platform}\0${name}`;
      if (!byKey.has(key)) {
        byKey.set(key, { platform, name });
      }
    });

    return [...byKey.values()].sort((a, b) => {
      const byPlatform = a.platform.localeCompare(b.platform, "pt-BR");
      if (byPlatform !== 0) {
        return byPlatform;
      }
      return a.name.localeCompare(b.name, "pt-BR", { sensitivity: "base" });
    });
  }

  function restreamReplayMessages() {
    const cards = queryAll(
      document,
      [
        '[id^="message-card-studio-"]',
        '[data-testid*="message" i]',
        '[class*="message-card" i]',
        '[class*="chat-message" i]',
        '[role="listitem"]',
      ].join(", "),
    );

    const seen = new Set();
    return cards
      .map((card) => {
        const platform = restreamCardPlatform(card);
        const author = restreamRawAuthorFromCard(card, platform);
        const clock = restreamClockFromCard(card);
        const text = restreamTextFromCard(card);
        return { clock, platform, channel: "", author, text };
      })
      .filter((message) => {
        if (!message.clock || !message.author || !message.text) {
          return false;
        }
        if (message.author === "Host" && message.text === "Read & reply to messages from multiple platforms here.") {
          return false;
        }
        const key = `${message.clock}\0${message.platform}\0${message.author}\0${message.text}`;
        if (seen.has(key)) {
          return false;
        }
        seen.add(key);
        return true;
      });
  }

  function copyRestreamReplayJson() {
    const messages = restreamReplayMessages();
    if (!messages.length) {
      window.alert("No Restream chat messages found in the currently loaded page.");
      return;
    }

    copyText(
      JSON.stringify(
        {
          source: "restream-userscript",
          exportedAt: new Date().toISOString(),
          pageUrl: location.href,
          messages,
        },
        null,
        2,
      ),
    );
  }

  function mergeSupporters(state, supporters) {
    const byKey = new Map();

    (state.supporters || []).forEach((supporter) => {
      const key = `${supporter.platform || ""}\0${supporter.name || ""}`;
      if (supporter.name && !isSelfSupporter(supporter.platform, supporter.name)) {
        byKey.set(key, supporter);
      }
    });

    supporters.forEach((supporter) => {
      if (isSelfSupporter(supporter.platform, supporter.name)) {
        return;
      }

      const url = restreamSupporterUrl(supporter.platform, supporter.name);
      const key = `${supporter.platform || ""}\0${supporter.name || ""}`;
      byKey.set(key, { ...supporter, url });
    });

    state.supporters = [...byKey.values()].sort((a, b) => {
      const byPlatform = String(a.platform || "").localeCompare(String(b.platform || ""), "pt-BR");
      if (byPlatform !== 0) {
        return byPlatform;
      }
      return String(a.name || "").localeCompare(String(b.name || ""), "pt-BR", { sensitivity: "base" });
    });
    saveState(state);

    return supporters.length;
  }

  function resetSession(state) {
    if (!window.confirm("Clear this session scratchpad?")) {
      return state;
    }

    const next = { ...DEFAULT_STATE, active: true };
    saveState(next);
    return next;
  }

  function renderPanel() {
    document.getElementById(PANEL_ID)?.remove();

    const state = loadState();
    const isLichessPage = location.hostname === "lichess.org";
    const isRestreamChatPage = isRestreamPage();
    const gameContext = currentGameContext();
    const canAddGame = Boolean(gameContext);
    const disabledUnlessLichess = isLichessPage ? "" : ' disabled title="Available on Lichess only"';
    const disabledUnlessGame = canAddGame ? "" : ' disabled title="Open a Lichess or Chess.com game first"';
    const scannedRestreamSupporters = isRestreamChatPage ? restreamSupporters() : [];
    const restreamCount = isRestreamChatPage ? scannedRestreamSupporters.length : 0;
    const restreamReplayCount = isRestreamChatPage ? restreamReplayMessages().length : 0;
    const savedSupporterCount = (state.supporters || []).length;
    const previewText = buildToml(state);
    const panel = document.createElement("section");
    panel.id = PANEL_ID;
    panel.className = state.collapsed ? "is-collapsed" : "";
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
        #${PANEL_ID}.is-collapsed {
          width: auto;
          padding: 6px;
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
        #${PANEL_ID} button:disabled {
          cursor: not-allowed;
          opacity: 0.45;
        }
        #${PANEL_ID} button:disabled:hover {
          border-color: #34372e;
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
        #${PANEL_ID}.is-collapsed .xlc-full {
          display: none;
        }
        #${PANEL_ID}:not(.is-collapsed) .xlc-collapsed {
          display: none;
        }
      </style>
      <div class="xlc-collapsed">
        <button type="button" data-action="toggle-collapse">xadrez.live</button>
      </div>
      <div class="xlc-full">
        <h2>xadrez.live</h2>
        <p class="xlc-meta">
          Attempts: ${state.attempts.length}
          · current: ${state.currentPuzzles.length} puzzle(s)
          · games: ${state.games.length}
        </p>
        <p class="xlc-meta">
          Puzzle of the day: ${state.puzzleOfTheDayUrl ? "ok" : "pending"}
          · stats: ${state.duration && state.rapid && state.puzzles ? "ok" : "pending"}
          · notes: ${state.descriptionNotes ? "ok" : "empty"}
          · supporters: ${savedSupporterCount}
        </p>
        ${
          isRestreamChatPage
            ? `<p class="xlc-meta">Restream chat: ${restreamCount} supporter(s), ${restreamReplayCount} replay message(s) loaded</p>`
            : ""
        }
        <div class="xlc-row">
          <button type="button" data-action="set-puzzle-of-day"${disabledUnlessLichess}>Puzzle of day</button>
          <button type="button" data-action="add-puzzle"${disabledUnlessLichess}>Add puzzle</button>
          <button type="button" data-action="add-puzzles"${disabledUnlessLichess}>Add puzzles</button>
        </div>
        <div class="xlc-row">
          <button type="button" data-action="finish-attempt"${disabledUnlessLichess}>Finish attempt</button>
          <button type="button" data-action="add-game"${disabledUnlessGame}>Add game</button>
        </div>
        <div class="xlc-row">
          <button type="button" data-action="set-post-stats"${disabledUnlessLichess}>Post stats</button>
          <button type="button" data-action="set-description-notes">Notes</button>
        </div>
        <div class="xlc-row">
          <button type="button" data-action="copy">Copy TOML</button>
          <button type="button" data-action="refresh">Refresh</button>
        </div>
        ${
          isRestreamChatPage
            ? `<div class="xlc-row">
                <button type="button" data-action="scan-restream-thanks">Add chat thanks</button>
                <button type="button" data-action="copy-restream-replay">Copy chat JSON</button>
              </div>`
            : ""
        }
        <div class="xlc-row">
          <button type="button" data-action="reset">New session</button>
          <button type="button" data-action="toggle-collapse">Collapse</button>
        </div>
        <textarea readonly spellcheck="false">${escapeHtml(previewText)}</textarea>
      </div>
    `;

    panel.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) {
        return;
      }

      let nextState = loadState();
      switch (button.dataset.action) {
        case "toggle-collapse":
          nextState.collapsed = !nextState.collapsed;
          saveState(nextState);
          break;
        case "set-puzzle-of-day":
          setPuzzleOfTheDay(nextState);
          break;
        case "add-puzzle":
          addCurrentPuzzle(nextState);
          break;
        case "add-puzzles":
          syncCurrentPuzzleSession(nextState);
          break;
        case "finish-attempt":
          finishAttempt(nextState);
          break;
        case "add-game":
          await addCurrentGame(nextState);
          break;
        case "set-post-stats":
          await setPostStats(nextState);
          break;
        case "set-description-notes":
          await setDescriptionNotes(nextState);
          break;
        case "copy":
          if (isRestreamPage()) {
            const supporters = restreamSupporters();
            if (!supporters.length) {
              window.alert("No Restream usernames found in the currently loaded page.");
            }
            mergeSupporters(nextState, supporters);
          }
          copyText(buildToml(nextState));
          break;
        case "scan-restream-thanks":
          {
            const count = mergeSupporters(nextState, restreamSupporters());
            window.alert(
              count
                ? `Added ${count} Restream supporter(s) to the TOML scratchpad.`
                : "No Restream usernames found in the currently loaded page.",
            );
          }
          break;
        case "copy-restream-replay":
          copyRestreamReplayJson();
          break;
        case "reset":
          nextState = resetSession(nextState);
          break;
        case "refresh":
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
