// ==UserScript==
// @name         xadrez.live Session Collector
// @namespace    https://xadrez.live/
// @version      0.24.0
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
  const LICHESS_SELF_USERNAMES = new Set(["fcz"]);
  const SELF_SUPPORTERS = {
    YouTube: new Set(["fczuardi"]),
    Twitch: new Set(["sedentarismo"]),
  };
  const SELF_SUPPORTER_HANDLES = new Set(Object.values(SELF_SUPPORTERS).flatMap((handles) => [...handles]));
  const AGGREGATOR_SUPPORTER_PLATFORMS = new Set(["Restream", "Restream.io"]);

  const DEFAULT_STATE = {
    active: false,
    collapsed: false,
    puzzleOfTheDayUrl: "",
    puzzleOfTheDayRecordedAt: "",
    duration: "",
    rapid: "",
    puzzles: "",
    descriptionNotes: "",
    practiceNotes: "",
    practiceNotesRecordedAt: "",
    attempts: [],
    currentPuzzles: [],
    practiceSets: [],
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

  function normalizePracticeUrl(url) {
    const match = /^https:\/\/lichess\.org\/practice\/([^/?#]+)\/([^/?#]+)\/([^/?#]+)(?:\/([^/?#]+))?/.exec(url);
    if (!match) {
      return null;
    }

    const base = `https://lichess.org/practice/${match[1]}/${match[2]}/${match[3]}`;
    return {
      category: match[1],
      slug: match[2],
      setId: match[3],
      exerciseId: match[4] || "",
      setUrl: base,
      exerciseUrl: match[4] ? `${base}/${match[4]}` : "",
    };
  }

  function titleFromSlug(slug) {
    return String(slug || "")
      .split("-")
      .filter(Boolean)
      .map((part) => (/^[ivxlcdm]+$/i.test(part) ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1)))
      .join(" ");
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

  function normalizeColor(value) {
    const color = String(value || "").trim().toLowerCase();
    return color === "black" || color === "white" ? color : "";
  }

  function normalizeLichessGameUrl(url, color = "") {
    const match = /^https:\/\/lichess\.org\/([A-Za-z0-9]{8})(?:\/(white|black))?/.exec(url);
    if (!match) {
      return "";
    }

    const side = normalizeColor(color) || match[2] || "";
    return `https://lichess.org/${match[1]}${side ? `/${side}` : ""}`;
  }

  function lichessGameIdFromUrl(url) {
    const match = /^https:\/\/lichess\.org\/([A-Za-z0-9]{8})/.exec(url);
    return match ? match[1] : "";
  }

  function normalizeLichessUsername(value) {
    return String(value || "").trim().replace(/^@/, "").toLowerCase();
  }

  function pgnTag(pgn, tag) {
    const pattern = new RegExp(`^\\[${tag}\\s+"((?:\\\\.|[^"\\\\])*)"\\]`, "m");
    const match = pattern.exec(pgn);
    return match ? match[1].replace(/\\"/g, '"').trim() : "";
  }

  function resultForColor(pgnResult, color) {
    const result = String(pgnResult || "").trim();
    if (result === "1/2-1/2") {
      return "draw";
    }
    if (color === "white") {
      return result === "1-0" ? "win" : result === "0-1" ? "loss" : "";
    }
    if (color === "black") {
      return result === "0-1" ? "win" : result === "1-0" ? "loss" : "";
    }
    return "";
  }

  async function lichessGameFactsFromExport(gameUrl) {
    const id = lichessGameIdFromUrl(gameUrl);
    if (!id) {
      return {};
    }

    try {
      const response = await fetch(`https://lichess.org/game/export/${id}?tags=true&clocks=false&evals=false`, {
        credentials: "same-origin",
        headers: { Accept: "application/x-chess-pgn,text/plain;q=0.9,*/*;q=0.1" },
      });
      if (!response.ok) {
        return {};
      }

      const pgn = await response.text();
      const white = normalizeLichessUsername(pgnTag(pgn, "White"));
      const black = normalizeLichessUsername(pgnTag(pgn, "Black"));
      const pgnResult = pgnTag(pgn, "Result");
      let color = "";
      if (LICHESS_SELF_USERNAMES.has(white)) {
        color = "white";
      } else if (LICHESS_SELF_USERNAMES.has(black)) {
        color = "black";
      }

      return {
        color,
        result: resultForColor(pgnResult, color),
      };
    } catch (_) {
      return {};
    }
  }

  function normalizeChessComGameUrl(url) {
    const match = /^https:\/\/www\.chess\.com\/(?:analysis\/)?game\/live\/(\d+)/.exec(url);
    return match ? `https://www.chess.com/analysis/game/live/${match[1]}` : "";
  }

  function currentGameContext() {
    const lichessUrl = normalizeLichessGameUrl(location.href);
    if (lichessUrl) {
      const colorFromUrl = /\/black(?:[?#]|$)/.test(location.href)
        ? "black"
        : /\/white(?:[?#]|$)/.test(location.href)
          ? "white"
          : "";
      return {
        platform: "lichess",
        gameUrl: lichessUrl,
        colorFromUrl,
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

  function currentLichessGameNote() {
    if (location.hostname !== "lichess.org") {
      return "";
    }
    const note = document.querySelector(".mchat__note");
    return String(note?.value || "").trim();
  }

  function preferredGameNote(existingNote) {
    const saved = String(existingNote || "").trim();
    const lichess = currentLichessGameNote();
    return lichess.length > saved.length ? lichess : saved;
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

  function tomlString(value) {
    const text = String(value || "");
    return text.includes("\n") ? `"""${multilineQuote(text)}"""` : `"${quote(text)}"`;
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

  function promptTextareaValue(label, fallback = "") {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.innerHTML = `
        <style>
          .xlc-textarea-overlay {
            position: fixed;
            inset: 0;
            z-index: 100000;
            display: grid;
            place-items: center;
            background: rgba(0, 0, 0, 0.45);
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          .xlc-textarea-dialog {
            width: min(560px, calc(100vw - 32px));
            border: 1px solid #5f6b75;
            border-radius: 8px;
            padding: 16px;
            background: #fffaf0;
            color: #132744;
            box-shadow: 0 18px 60px rgba(0, 0, 0, 0.28);
          }
          .xlc-textarea-dialog label {
            display: grid;
            gap: 8px;
            font-weight: 700;
          }
          .xlc-textarea-dialog textarea {
            min-height: 180px;
            resize: vertical;
            border: 1px solid #d9cdb8;
            border-radius: 6px;
            padding: 10px;
            color: inherit;
            background: #fff;
            font: inherit;
            line-height: 1.45;
          }
          .xlc-textarea-actions {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            margin-top: 12px;
          }
          .xlc-textarea-actions button {
            min-height: 34px;
            border: 1px solid #d9cdb8;
            border-radius: 6px;
            padding: 0 12px;
            background: #fff;
            color: inherit;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
          }
          .xlc-textarea-actions button[type="submit"] {
            border-color: #42562c;
            background: #42562c;
            color: #fffaf0;
          }
        </style>
        <div class="xlc-textarea-overlay">
          <form class="xlc-textarea-dialog">
            <label>
              ${escapeHtml(label)}
              <textarea name="value" spellcheck="true">${escapeHtml(fallback)}</textarea>
            </label>
            <div class="xlc-textarea-actions">
              <button type="button" data-action="cancel">Cancel</button>
              <button type="submit">Save</button>
            </div>
          </form>
        </div>
      `;
      document.body.appendChild(overlay);
      const form = overlay.querySelector("form");
      const textarea = overlay.querySelector("textarea");

      function close(value) {
        overlay.remove();
        resolve(value);
      }

      textarea.focus();
      textarea.selectionStart = textarea.value.length;
      textarea.selectionEnd = textarea.value.length;
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        close(textarea.value.trim());
      });
      form.querySelector('[data-action="cancel"]').addEventListener("click", () => close(fallback));
    });
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

  async function setPracticeNotes(state) {
    const notes = await promptTextareaValue(
      "Practice notes (puzzles and study before the rapid game):",
      state.practiceNotes,
    );
    state.practiceNotes = notes;
    state.practiceNotesRecordedAt = new Date().toISOString();
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
    state.puzzleOfTheDayRecordedAt = new Date().toISOString();
    saveState(state);
  }

  function practiceSetTitle(meta) {
    const heading = [
      ".practice__side h1",
      ".practice__side h2",
      ".practice__side__info h1",
      ".practice__side__info h2",
      "main h1",
    ]
      .map((selector) => document.querySelector(selector))
      .map((element) => String(element?.textContent || "").replace(/\s+/g, " ").trim())
      .find(Boolean);

    return heading || titleFromSlug(meta.slug);
  }

  function practiceChapterStatus(chapter) {
    const status = chapter.querySelector(".status");
    if (status?.classList.contains("done")) {
      return "done";
    }
    if (status?.classList.contains("ongoing")) {
      return "ongoing";
    }
    return "";
  }

  function practiceExerciseFromChapter(chapter) {
    const href = chapter.getAttribute("href") || "";
    const url = normalizePracticeUrl(new URL(href, location.origin).href);
    if (!url?.exerciseUrl) {
      return null;
    }

    const title = String(chapter.querySelector("h3")?.textContent || "").replace(/\s+/g, " ").trim();
    if (!title) {
      return null;
    }

    return {
      title,
      url: url.exerciseUrl,
      status: practiceChapterStatus(chapter),
    };
  }

  function currentPracticeContext() {
    if (location.hostname !== "lichess.org") {
      return null;
    }

    const meta = normalizePracticeUrl(location.href);
    if (!meta) {
      return null;
    }

    const activeChapter = document.querySelector(".practice__side__chapters .ps__chapter.active");
    const activeExercise = activeChapter ? practiceExerciseFromChapter(activeChapter) : null;
    return {
      platform: "lichess",
      title: practiceSetTitle(meta),
      url: meta.setUrl,
      category: meta.category,
      currentExercise: activeExercise,
      doneExercises: [...document.querySelectorAll(".practice__side__chapters .ps__chapter")]
        .filter((chapter) => chapter.querySelector(".status.done"))
        .map(practiceExerciseFromChapter)
        .filter(Boolean),
    };
  }

  function mergePracticeExercises(state, context, exercises) {
    if (!context || !exercises.length) {
      return 0;
    }

    const sets = [...(state.practiceSets || [])];
    let setIndex = sets.findIndex((set) => set.url === context.url);
    if (setIndex === -1) {
      sets.push({
        platform: context.platform,
        title: context.title,
        url: context.url,
        category: context.category,
        exercises: [],
      });
      setIndex = sets.length - 1;
    }

    const set = {
      ...sets[setIndex],
      platform: sets[setIndex].platform || context.platform,
      title: sets[setIndex].title || context.title,
      url: sets[setIndex].url || context.url,
      category: sets[setIndex].category || context.category,
      exercises: [...(sets[setIndex].exercises || [])],
    };
    const byUrl = new Map(set.exercises.map((exercise) => [exercise.url, exercise]));
    let added = 0;

    exercises.forEach((exercise) => {
      if (!exercise?.url || !exercise?.title) {
        return;
      }
      if (!byUrl.has(exercise.url)) {
        added += 1;
      }
      byUrl.set(exercise.url, {
        ...byUrl.get(exercise.url),
        title: exercise.title,
        url: exercise.url,
        status: exercise.status || byUrl.get(exercise.url)?.status || "",
      });
    });

    set.exercises = [...byUrl.values()];
    sets[setIndex] = set;
    state.practiceSets = sets;
    saveState(state);

    return added;
  }

  function addCurrentPracticeExercise(state) {
    const context = currentPracticeContext();
    if (!context?.currentExercise) {
      window.alert("Could not find the active Lichess practice exercise.");
      return;
    }

    const count = mergePracticeExercises(state, context, [context.currentExercise]);
    window.alert(count ? "Added current practice exercise." : "Practice exercise was already saved.");
  }

  function syncDonePracticeExercises(state) {
    const context = currentPracticeContext();
    if (!context?.doneExercises.length) {
      window.alert("Could not find completed Lichess practice exercises.");
      return;
    }

    const count = mergePracticeExercises(state, context, context.doneExercises);
    window.alert(
      count
        ? `Added ${count} completed practice exercise(s).`
        : "Completed practice exercises were already saved.",
    );
  }

  async function addCurrentGame(state) {
    const context = currentGameContext();
    if (!context) {
      window.alert("This URL does not look like a supported Lichess or Chess.com game.");
      return;
    }

    const detected = context.platform === "lichess" ? await lichessGameFactsFromExport(context.gameUrl) : {};
    if (context.platform === "lichess") {
      context.colorFromUrl = context.colorFromUrl || detected.color || "";
      context.gameUrl = normalizeLichessGameUrl(context.gameUrl, context.colorFromUrl);
    }

    const existingGameIndex = state.games.findIndex((game) => {
      const gameUrl = game.game_url || game.lichess_game_url || "";
      if (context.platform === "lichess") {
        return lichessGameIdFromUrl(gameUrl) === lichessGameIdFromUrl(context.gameUrl);
      }
      return gameUrl === context.gameUrl;
    });
    const existingGame = existingGameIndex === -1 ? {} : state.games[existingGameIndex];
    const existingColor = normalizeColor(existingGame.color);
    const color =
      existingColor ||
      context.colorFromUrl ||
      (await selectValue(
        "Color",
        [
          { value: "", label: "Not set" },
          { value: "white", label: "white" },
          { value: "black", label: "black" },
        ],
        "",
      ));
    const result =
      existingGame.result ||
      detected.result ||
      (await selectValue(
        "Result",
        [
          { value: "", label: "Not set" },
          { value: "win", label: "win" },
          { value: "loss", label: "loss" },
          { value: "draw", label: "draw" },
        ],
        "",
      ));
    const game = {
      platform: context.platform,
      game_url: context.platform === "lichess" ? normalizeLichessGameUrl(context.gameUrl, color) : context.gameUrl,
      result,
      color,
      note: await promptTextareaValue("Optional game note:", preferredGameNote(existingGame.note)),
    };

    if (context.platform === "lichess") {
      game.game_id = lichessGameIdFromUrl(context.gameUrl);
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
      if (state.puzzleOfTheDayRecordedAt) {
        blocks.push(`puzzle_of_the_day_recorded_at = "${quote(state.puzzleOfTheDayRecordedAt)}"`);
        blocks.push('puzzle_of_the_day_event = "puzzle_of_the_day"');
      }
    }

    if (state.duration || state.rapid || state.puzzles) {
      blocks.push(`duration = "${quote(state.duration)}"
rapid = "${quote(state.rapid)}"
puzzles = "${quote(state.puzzles)}"`);
    }

    if (state.descriptionNotes) {
      blocks.push(`description_notes = """${multilineQuote(state.descriptionNotes)}"""`);
    }

    if (state.practiceNotes) {
      blocks.push(`practice_notes = """${multilineQuote(state.practiceNotes)}"""`);
      if (state.practiceNotesRecordedAt) {
        blocks.push(`practice_notes_recorded_at = "${quote(state.practiceNotesRecordedAt)}"`);
        blocks.push('practice_notes_event = "practice_end"');
      }
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

    (state.practiceSets || []).forEach((set) => {
      const lines = ["[[extra.practice_sets]]"];
      lines.push(`platform = "${quote(set.platform)}"`);
      lines.push(`title = "${quote(set.title)}"`);
      lines.push(`url = "${quote(set.url)}"`);
      if (set.category) {
        lines.push(`category = "${quote(set.category)}"`);
      }
      (set.exercises || []).forEach((exercise) => {
        lines.push("");
        lines.push("[[extra.practice_sets.exercises]]");
        lines.push(`title = "${quote(exercise.title)}"`);
        lines.push(`url = "${quote(exercise.url)}"`);
        if (exercise.status) {
          lines.push(`status = "${quote(exercise.status)}"`);
        }
      });
      blocks.push(lines.join("\n"));
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
      if (game.game_id) {
        lines.push(`game_id = "${quote(game.game_id)}"`);
      }
      lines.push(`result = "${quote(game.result)}"`);
      lines.push(`color = "${quote(game.color)}"`);
      if (game.opening) {
        lines.push(`opening = "${quote(game.opening)}"`);
      }
      if (game.opening_url) {
        lines.push(`opening_url = "${quote(game.opening_url)}"`);
      }
      lines.push(`note = ${tomlString(game.note)}`);
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

  function downloadTextFile(filename, text, type) {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function saveTextFile(filename, text, type = "text/plain") {
    if (!text) {
      window.alert("Nothing to save yet.");
      return;
    }

    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: filename,
          types: [
            {
              description: type.includes("json") ? "JSON" : "TOML",
              accept: { [type]: [filename.slice(filename.lastIndexOf("."))] },
            },
          ],
        });
        const writable = await handle.createWritable();
        await writable.write(text);
        await writable.close();
        window.alert(`Saved ${filename}.`);
        return;
      } catch (error) {
        if (error?.name === "AbortError") {
          return;
        }
      }
    }

    downloadTextFile(filename, text, type);
    window.alert(`Downloaded ${filename}.`);
  }

  function promptSessionNumber() {
    const value = window.prompt("Session number, e.g. 0054:", "");
    const trimmed = String(value || "").trim();
    if (!trimmed) {
      return "";
    }
    return trimmed.padStart(4, "0");
  }

  async function saveTomlFile(state) {
    const sessionNumber = promptSessionNumber();
    if (!sessionNumber) {
      return;
    }
    const generated = buildToml(state);
    await saveTextFile(`${sessionNumber}.toml`, currentPanelToml(generated), "application/toml");
  }

  function currentPanelToml(fallback) {
    const panelTextarea = document.querySelector(`#${PANEL_ID} textarea`);
    if (!panelTextarea) {
      return fallback;
    }
    const editedText = panelTextarea.value.trim();
    return editedText || fallback;
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
    if (/restream/i.test(value) || value.includes("restream-icon-")) {
      return "Restream";
    }
    return "";
  }

  function restreamCardPlatformIcon(card) {
    return queryAll(card, 'img.icon-platform, img[src*="restream.io/img/api/platforms/platform-"], img[src*="restream-icon-"]')
      .filter((element) => !/^status$/i.test(String(element.getAttribute("alt") || "")))
      .map((element) => element.getAttribute("src"))
      .find(Boolean) || "";
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

  function platformFromProfileHref(href) {
    const value = String(href || "");
    if (/youtube\.com\/@/i.test(value)) {
      return "YouTube";
    }
    if (/twitch\.tv\//i.test(value)) {
      return "Twitch";
    }
    return "";
  }

  function restreamCardAuthorLabel(card) {
    return queryAll(
      card,
      [
        ".MuiTypography-subtitle2",
        ".message-sender",
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
      .map((element) =>
        String(element.textContent || "")
          .replace(/[\u200b-\u200d\ufeff]/g, "")
          .replace(/\s+/g, " ")
          .trim(),
      )
      .find(Boolean) || "";
  }

  function restreamCardPlatform(card) {
    const profilePlatform = queryAll(card, 'a[href*="youtube.com/@"], a[href*="twitch.tv/"]')
      .map((link) => platformFromProfileHref(link.getAttribute("href")))
      .find(Boolean);
    if (profilePlatform) {
      return profilePlatform;
    }

    const platformIcon = restreamCardPlatformIcon(card);
    const platformFromIcon = restreamPlatformFromSrc(platformIcon);
    if (platformFromIcon && platformFromIcon !== "Restream") {
      return platformFromIcon;
    }

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

    const uniquePlatforms = [...new Set(platforms)];
    const realPlatform = uniquePlatforms.find((platform) => platform !== "Restream");
    if (realPlatform) {
      return realPlatform;
    }
    if (platformFromIcon || uniquePlatforms.includes("Restream") || /^Restream(?:\.io)?$/i.test(restreamCardAuthorLabel(card))) {
      return "Restream";
    }
    return "Chat";
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

  function isRestreamSystemMessage(message) {
    const text = String(message?.text || "").trim();
    return (
      message.author === "Host" &&
      /^(Read & reply to messages from multiple platforms here\.|The chat is ready to display messages\.|Start the conversation|New comments will display here)$/i.test(
        text,
      )
    );
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

  function restreamClockFromEmbedMessage(message) {
    const value = queryAll(
      message,
      [
        ".message-time",
        ".message-timestamp",
        "time",
        "[datetime]",
        '[class*="time" i]',
        '[class*="timestamp" i]',
      ].join(", "),
    )
      .map((element) => element.getAttribute("datetime") || element.textContent)
      .map((text) => String(text || "").trim())
      .find((text) => /^\d{1,2}:\d{2}:\d{2}$/.test(text));
    return value || "";
  }

  function restreamTextFromEmbedMessage(message) {
    const value = queryAll(
      message,
      [
        ".message-text",
        ".message-body",
        ".message-content",
        ".chat-text-normal",
        '[data-testid*="message" i]',
        '[class*="message-text" i]',
      ].join(", "),
    )
      .map((element) => String(element.textContent || "").replace(/\s+/g, " ").trim())
      .find(Boolean);
    return value || "";
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
    const handle = normalizedSupporterHandle(name);
    return SELF_SUPPORTERS[platform]?.has(handle) || SELF_SUPPORTER_HANDLES.has(handle) || false;
  }

  function isAggregatorSupporterPlatform(platform) {
    return AGGREGATOR_SUPPORTER_PLATFORMS.has(String(platform || "").trim());
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
      if (isAggregatorSupporterPlatform(platform) || isSelfSupporter(platform, name)) {
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
      if (isAggregatorSupporterPlatform(platform) || isSelfSupporter(platform, name)) {
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
    const adminCards = queryAll(document, '[id^="message-card-studio-"]');
    const embedMessages = queryAll(document, ".chat-messages .message-item, .message-item");

    const seen = new Set();
    const messages = adminCards
      .map((card) => {
        const platform = restreamCardPlatform(card);
        const platformIcon = restreamCardPlatformIcon(card);
        const author = restreamRawAuthorFromCard(card, platform);
        const clock = restreamClockFromCard(card);
        const text = restreamTextFromCard(card);
        return { clock, platform, platformIcon, channel: "", author, text };
      });

    embedMessages.forEach((message) => {
      const platform = restreamCardPlatform(message);
      const platformIcon = restreamCardPlatformIcon(message);
      const author = restreamAuthorFromEmbedMessage(message) || "Host";
      const clock = restreamClockFromEmbedMessage(message);
      const text = restreamTextFromEmbedMessage(message);
      messages.push({ clock, platform, platformIcon, channel: "", author, text });
    });

    return messages.filter((message) => {
        if (!message.clock || !message.author || !message.text) {
          return false;
        }
        if (isRestreamSystemMessage(message)) {
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

  function restreamReplayJsonText() {
    const messages = restreamReplayMessages();
    if (!messages.length) {
      window.alert("No Restream chat messages found in the currently loaded page.");
      return "";
    }

    return JSON.stringify(
      {
        source: "restream-userscript",
        exportedAt: new Date().toISOString(),
        pageUrl: location.href,
        messages,
      },
      null,
      2,
    );
  }

  function copyRestreamReplayJson() {
    const text = restreamReplayJsonText();
    if (text) {
      copyText(text);
    }
  }

  async function saveRestreamReplayJson() {
    const sessionNumber = promptSessionNumber();
    if (!sessionNumber) {
      return;
    }
    const text = restreamReplayJsonText();
    if (text) {
      await saveTextFile(`${sessionNumber}-chat.json`, text, "application/json");
    }
  }

  function mergeSupporters(state, supporters) {
    const byKey = new Map();
    let mergedCount = 0;

    (state.supporters || []).forEach((supporter) => {
      const key = `${supporter.platform || ""}\0${supporter.name || ""}`;
      if (
        supporter.name &&
        !isAggregatorSupporterPlatform(supporter.platform) &&
        !isSelfSupporter(supporter.platform, supporter.name)
      ) {
        byKey.set(key, supporter);
      }
    });

    supporters.forEach((supporter) => {
      if (isAggregatorSupporterPlatform(supporter.platform) || isSelfSupporter(supporter.platform, supporter.name)) {
        return;
      }

      const url = restreamSupporterUrl(supporter.platform, supporter.name);
      const key = `${supporter.platform || ""}\0${supporter.name || ""}`;
      byKey.set(key, { ...supporter, url });
      mergedCount += 1;
    });

    state.supporters = [...byKey.values()].sort((a, b) => {
      const byPlatform = String(a.platform || "").localeCompare(String(b.platform || ""), "pt-BR");
      if (byPlatform !== 0) {
        return byPlatform;
      }
      return String(a.name || "").localeCompare(String(b.name || ""), "pt-BR", { sensitivity: "base" });
    });
    saveState(state);

    return mergedCount;
  }

  function resetSession(state) {
    if (!window.confirm("Clear this session scratchpad?")) {
      return state;
    }

    const next = { ...DEFAULT_STATE, active: true };
    saveState(next);
    return next;
  }

  function isFramedWindow() {
    try {
      return window.self !== window.top;
    } catch (_) {
      return true;
    }
  }

  function renderPanel() {
    document.getElementById(PANEL_ID)?.remove();

    const state = loadState();
    const isLichessPage = location.hostname === "lichess.org";
    const isRestreamChatPage = isRestreamPage();
    const gameContext = currentGameContext();
    const practiceContext = currentPracticeContext();
    const canAddGame = Boolean(gameContext);
    const canAddPractice = Boolean(practiceContext);
    const disabledUnlessLichess = isLichessPage ? "" : ' disabled title="Available on Lichess only"';
    const disabledUnlessGame = canAddGame ? "" : ' disabled title="Open a Lichess or Chess.com game first"';
    const disabledUnlessPractice = canAddPractice ? "" : ' disabled title="Open a Lichess practice exercise first"';
    const scannedRestreamSupporters = isRestreamChatPage ? restreamSupporters() : [];
    const restreamCount = isRestreamChatPage ? scannedRestreamSupporters.length : 0;
    const restreamReplayCount = isRestreamChatPage ? restreamReplayMessages().length : 0;
    const savedSupporterCount = (state.supporters || []).length;
    const savedPracticeCount = (state.practiceSets || []).reduce(
      (total, set) => total + ((set.exercises || []).length),
      0,
    );
    const previewText = buildToml(state);
    const panel = document.createElement("section");
    panel.id = PANEL_ID;
    panel.className = [state.collapsed ? "is-collapsed" : "", isFramedWindow() ? "is-framed" : ""]
      .filter(Boolean)
      .join(" ");
    panel.innerHTML = `
      <style>
        #${PANEL_ID} {
          position: fixed;
          right: 16px;
          bottom: 16px;
          z-index: 99999;
          width: min(360px, calc(100vw - 32px));
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
        #${PANEL_ID}.is-framed {
          bottom: 66px;
        }
        #${PANEL_ID} h2 {
          margin: 0 0 8px;
          color: #d8a657;
          font-size: 13px;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        #${PANEL_ID} .xlc-full {
          display: block;
        }
        #${PANEL_ID} .xlc-controls,
        #${PANEL_ID} .xlc-preview {
          min-width: 0;
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
          min-height: 280px;
          margin-top: 6px;
          padding: 8px;
          background: #0f110d;
          color: #f2f0e7;
          font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
          resize: vertical;
          white-space: pre;
        }
        #${PANEL_ID} .xlc-meta {
          margin: 0 0 8px;
          color: #b8b5a8;
          font-size: 12px;
        }
        #${PANEL_ID} .xlc-preview-label {
          display: block;
          margin-top: 6px;
          color: #b8b5a8;
          font-size: 12px;
        }
        #${PANEL_ID} .xlc-section-label {
          margin: 10px 0 5px;
          color: #d8a657;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        #${PANEL_ID} .xlc-fallback button {
          border-color: #735f32;
          background: #2c2618;
          color: #f0d89b;
        }
        #${PANEL_ID} .xlc-fallback button:only-child {
          grid-column: 1 / -1;
        }
        #${PANEL_ID} .xlc-fallback button:hover {
          border-color: #e0ad4f;
        }
        #${PANEL_ID}.is-collapsed .xlc-full {
          display: none;
        }
        #${PANEL_ID}:not(.is-collapsed) .xlc-collapsed {
          display: none;
        }
        @media (min-width: 720px) {
          #${PANEL_ID}:not(.is-collapsed) {
            width: min(760px, calc(100vw - 32px));
          }
          #${PANEL_ID} .xlc-full {
            display: grid;
            grid-template-columns: minmax(240px, 310px) minmax(360px, 1fr);
            gap: 10px;
            align-items: start;
          }
          #${PANEL_ID} .xlc-controls h2,
          #${PANEL_ID} .xlc-controls .xlc-meta:last-of-type {
            margin-bottom: 8px;
          }
          #${PANEL_ID} textarea {
            min-height: min(620px, calc(100vh - 130px));
          }
          #${PANEL_ID} .xlc-preview-label {
            margin-top: 0;
          }
        }
      </style>
      <div class="xlc-collapsed">
        <button type="button" data-action="toggle-collapse">xadrez.live</button>
      </div>
      <div class="xlc-full">
        <div class="xlc-controls">
          <h2>xadrez.live</h2>
          <p class="xlc-meta">
            Attempts: ${state.attempts.length}
            · current: ${state.currentPuzzles.length} puzzle(s)
            · games: ${state.games.length}
            · practice: ${savedPracticeCount}
          </p>
          <p class="xlc-meta">
            Puzzle of the day: ${state.puzzleOfTheDayUrl ? "ok" : "pending"}
          · practice notes: ${state.practiceNotes ? "ok" : "empty"}
          · supporters: ${savedSupporterCount}
          </p>
          ${
            isRestreamChatPage
              ? `<p class="xlc-meta">Restream chat: ${restreamCount} chat participant(s), ${restreamReplayCount} replay message(s) loaded</p>`
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
            <button type="button" data-action="add-practice"${disabledUnlessPractice}>Add practice</button>
          </div>
          <div class="xlc-row">
            <button type="button" data-action="set-practice-notes">Practice notes</button>
          </div>
          <div class="xlc-row">
            <button type="button" data-action="save-toml">Save TOML</button>
          </div>
          ${
            isRestreamChatPage
              ? `<div class="xlc-row">
                  <button type="button" data-action="save-restream-replay">Save chat JSON</button>
                </div>`
              : ""
          }
          <div class="xlc-row">
            <button type="button" data-action="reset">New session</button>
            <button type="button" data-action="toggle-collapse">Collapse</button>
          </div>
          <p class="xlc-section-label">Fallback</p>
          <div class="xlc-row xlc-fallback">
            <button type="button" data-action="copy">Copy TOML</button>
            ${
              isRestreamChatPage
                ? `<button type="button" data-action="copy-restream-replay">Copy chat JSON</button>`
                : ""
            }
          </div>
        </div>
        <div class="xlc-preview">
          <label class="xlc-preview-label" for="${PANEL_ID}-toml">TOML preview/edit</label>
          <textarea id="${PANEL_ID}-toml" spellcheck="false">${escapeHtml(previewText)}</textarea>
        </div>
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
        case "add-practice":
          addCurrentPracticeExercise(nextState);
          break;
        case "set-practice-notes":
          await setPracticeNotes(nextState);
          break;
        case "copy":
          {
            const generatedBeforeCopy = buildToml(nextState);
            let copyValue = currentPanelToml(generatedBeforeCopy);

            if (isRestreamPage()) {
              const supporters = restreamSupporters();
              if (!supporters.length) {
                window.alert("No Restream usernames found in the currently loaded page.");
              }
              mergeSupporters(nextState, supporters);

              const generatedAfterMerge = buildToml(nextState);
              if (copyValue === generatedBeforeCopy) {
                copyValue = generatedAfterMerge;
              }
            }

            copyText(copyValue);
          }
          break;
        case "save-toml":
          await saveTomlFile(nextState);
          break;
        case "copy-restream-replay":
          copyRestreamReplayJson();
          break;
        case "save-restream-replay":
          await saveRestreamReplayJson();
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
