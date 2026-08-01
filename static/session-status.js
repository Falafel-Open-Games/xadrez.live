(function () {
  var LIVE_WINDOW_MS = 6 * 60 * 60 * 1000;

  function localDateOnly(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function parseSessionDate(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) {
      return null;
    }

    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }

  function shortDate(date) {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
    }).format(date);
  }

  function scheduledLabel(date, time) {
    var today = localDateOnly(new Date());
    var sessionDate = localDateOnly(date);
    var diffDays = Math.round((sessionDate - today) / 86400000);

    if (diffDays === 0) {
      return "marcada para hoje às " + time;
    }

    if (diffDays === 1) {
      return "marcada para amanhã às " + time;
    }

    return "marcada para " + shortDate(date) + " às " + time;
  }

  function parseIsoDate(value) {
    var timestamp = Date.parse(value || "");
    if (Number.isNaN(timestamp)) {
      return null;
    }

    return new Date(timestamp);
  }

  document.querySelectorAll("[data-session-status]").forEach(function (element) {
    if (element.dataset.statusTone !== "scheduled") {
      return;
    }

    var date = parseSessionDate(element.dataset.sessionDate);
    var time = element.dataset.sessionTime;
    if (!date || !time) {
      return;
    }

    element.textContent = scheduledLabel(date, time);
  });

  document.querySelectorAll("[data-external-stream-status]").forEach(function (element) {
    var scheduledAt = parseIsoDate(element.dataset.scheduledAt);

    if (element.dataset.liveStatus === "is_live") {
      if (scheduledAt && scheduledAt.getTime() < Date.now() - LIVE_WINDOW_MS) {
        var item = element.closest("li");
        if (item) {
          item.hidden = true;
        }
        return;
      }

      element.textContent = "ao vivo agora";
      return;
    }

    if (!scheduledAt) {
      return;
    }

    if (
      scheduledAt.getTime() <= Date.now() &&
      scheduledAt.getTime() >= Date.now() - LIVE_WINDOW_MS
    ) {
      element.textContent = "ao vivo agora";
    }
  });

  document.querySelectorAll("[data-session-fold-button]").forEach(function (button) {
    button.addEventListener("click", function () {
      var section = button.closest(".session-list-section");
      if (!section) {
        return;
      }

      section.querySelectorAll(".session-fold-extra[hidden]").forEach(function (item) {
        item.hidden = false;
      });
      button.hidden = true;
    });
  });

  document.querySelectorAll("[data-replay-tabs]").forEach(function (section) {
    var playerFrame = document.querySelector("[data-youtube-player]");

    function shouldHandleReplayTimeClick(event) {
      return (
        event.button === 0 &&
        !event.defaultPrevented &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.shiftKey &&
        !event.altKey
      );
    }

    function seekEmbeddedPlayer(seconds) {
      if (!playerFrame || !playerFrame.contentWindow) {
        return false;
      }

      playerFrame.contentWindow.postMessage(
        JSON.stringify({
          event: "command",
          func: "seekTo",
          args: [Math.max(0, seconds), true],
        }),
        "https://www.youtube.com"
      );
      playerFrame.contentWindow.postMessage(
        JSON.stringify({
          event: "command",
          func: "playVideo",
          args: [],
        }),
        "https://www.youtube.com"
      );
      return true;
    }

    function sortMergedPanel() {
      var merged = section.querySelector('[data-replay-panel="merged"]');
      if (!merged) {
        return;
      }

      Array.from(merged.children)
        .sort(function (left, right) {
          var leftSeconds = Number(left.dataset.seconds || 0);
          var rightSeconds = Number(right.dataset.seconds || 0);
          var leftOrder = Number(left.dataset.order || 0);
          var rightOrder = Number(right.dataset.order || 0);
          return leftSeconds - rightSeconds || leftOrder - rightOrder;
        })
        .forEach(function (item) {
          merged.appendChild(item);
        });
    }

    function activeReplayTab() {
      var activeTab = section.querySelector("[data-replay-tab].is-active");
      if (activeTab) {
        return activeTab.dataset.replayTab;
      }
      var activePanel = section.querySelector("[data-replay-panel].is-active");
      return activePanel ? activePanel.dataset.replayPanel : "transcript";
    }

    function updateReplayPanels() {
      var target = activeReplayTab();
      panels.forEach(function (panel) {
        panel.classList.toggle("is-active", panel.dataset.replayPanel === target);
      });
      section.querySelectorAll(".transcript-source-tabs").forEach(function (tabs) {
        tabs.hidden = target === "chat";
      });
    }

    function transcriptSources() {
      var sources = {};
      section.querySelectorAll("[data-transcript-source-data]").forEach(function (script) {
        try {
          sources[script.dataset.transcriptSourceData] = {
            label: script.dataset.transcriptSourceLabel,
            blocks: JSON.parse(script.textContent || "[]"),
          };
        } catch (error) {
          sources[script.dataset.transcriptSourceData] = { label: "Transcrição", blocks: [] };
        }
      });
      return sources;
    }

    function createTranscriptItem(block, label, merged) {
      var item = document.createElement("li");
      item.className = "replay-item replay-item-transcript";
      item.dataset.transcriptGenerated = "true";
      item.dataset.seconds = String(block.seconds || 0);
      item.dataset.order = "1";

      var time = document.createElement("a");
      time.className = "replay-time";
      time.href = section.dataset.youtubeUrl + "&t=" + (block.seconds || 0) + "s";
      time.rel = "noopener noreferrer";
      time.textContent = block.time || "0:00";

      var body = document.createElement("div");
      body.className = "replay-body";
      if (merged) {
        var title = document.createElement("strong");
        var platform = document.createElement("span");
        platform.className = "chat-replay-platform";
        platform.textContent = label;
        title.append("Transcrição ", platform);
        body.appendChild(title);
      }

      var text = document.createElement("p");
      text.textContent = block.text || "";
      body.appendChild(text);
      item.append(time, body);
      return item;
    }

    function setTranscriptSource(sourceId) {
      var source = sources[sourceId];
      if (!source) {
        return;
      }

      section.querySelectorAll("[data-transcript-list]").forEach(function (list) {
        list.querySelectorAll("[data-transcript-generated]").forEach(function (item) {
          item.remove();
        });
        source.blocks.forEach(function (block) {
          list.appendChild(createTranscriptItem(block, source.label, list.dataset.transcriptList === "merged"));
        });
        list.dataset.transcriptSourceActive = sourceId;
      });
      sortMergedPanel();
    }

    var sources = transcriptSources();
    var tabs = Array.from(section.querySelectorAll("[data-replay-tab]"));
    var panels = Array.from(section.querySelectorAll("[data-replay-panel]"));
    sortMergedPanel();
    updateReplayPanels();

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (candidate) {
          var active = candidate === tab;
          candidate.classList.toggle("is-active", active);
          candidate.setAttribute("aria-selected", active ? "true" : "false");
        });
        updateReplayPanels();
      });
    });

    section.querySelectorAll("[data-transcript-source]").forEach(function (button) {
      button.addEventListener("click", function () {
        section.querySelectorAll("[data-transcript-source]").forEach(function (candidate) {
          var active = candidate === button;
          candidate.classList.toggle("is-active", active);
          candidate.setAttribute("aria-selected", active ? "true" : "false");
        });
        setTranscriptSource(button.dataset.transcriptSource);
        updateReplayPanels();
      });
    });

    section.addEventListener("click", function (event) {
      var link = event.target.closest(".replay-time");
      if (!link || !section.contains(link) || !shouldHandleReplayTimeClick(event)) {
        return;
      }

      var item = link.closest("[data-seconds]");
      var seconds = item ? Number(item.dataset.seconds || 0) : 0;
      if (!Number.isFinite(seconds) || !seekEmbeddedPlayer(seconds)) {
        return;
      }

      event.preventDefault();
    });
  });
})();
