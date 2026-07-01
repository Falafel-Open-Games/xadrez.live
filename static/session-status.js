(function () {
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
    if (element.dataset.liveStatus === "is_live") {
      element.textContent = "ao vivo agora";
      return;
    }

    var scheduledAt = parseIsoDate(element.dataset.scheduledAt);
    if (!scheduledAt) {
      return;
    }

    if (scheduledAt.getTime() <= Date.now()) {
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
