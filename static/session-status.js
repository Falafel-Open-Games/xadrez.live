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
})();
