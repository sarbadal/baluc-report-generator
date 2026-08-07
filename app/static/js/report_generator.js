(function () {
  const refreshButton = document.getElementById("refresh-reports-button");
  const queueBody = document.getElementById("queue-body");
  const queueCount = document.getElementById("queue-count");
  const queueEmpty = document.getElementById("queue-empty");
  const refreshNote = document.getElementById("refresh-note");
  if (!refreshButton || !queueBody || !queueCount || !queueEmpty) {
    return;
  }

  const statusUrl = String(refreshButton.dataset.statusUrl || "").trim();
  if (!statusUrl) {
    return;
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderJob(report) {
    const status = esc(report.status);
    const statusClass = esc(String(report.status || "").toLowerCase());
    const download = report.download_url
      ? '<a class="download" href="' + esc(report.download_url) + '">CSV</a>'
      : '<span class="job-meta dash">-</span>';
    const error = report.error ? '<p class="job-error">' + esc(report.error) + "</p>" : "";

    return (
      '<div class="job job-row">' +
      '<p class="job-name">' + esc(report.report_type) + "</p>" +
      '<p class="job-meta range">' + esc(report.start_date) + " to " + esc(report.end_date) + "</p>" +
      '<p class="job-meta requested">' + esc(report.requested_at) + "</p>" +
      '<span class="badge ' + statusClass + '">' + status + "</span>" +
      download +
      error +
      "</div>"
    );
  }

  async function refreshReports() {
    refreshButton.disabled = true;
    refreshButton.classList.add("is-refreshing");
    if (refreshNote) {
      refreshNote.textContent = "Refreshing...";
    }

    try {
      const response = await fetch(statusUrl, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error("Request failed");
      }

      const payload = await response.json();
      const reports = Array.isArray(payload.reports) ? payload.reports : [];

      queueCount.textContent = reports.length + " jobs shown";
      if (reports.length === 0) {
        queueBody.innerHTML = "";
        queueBody.style.display = "none";
        queueEmpty.style.display = "block";
      } else {
        queueBody.innerHTML = reports.map(renderJob).join("");
        queueBody.style.display = "grid";
        queueEmpty.style.display = "none";
      }

      if (refreshNote) {
        refreshNote.textContent = "Updated.";
      }
    } catch (_error) {
      if (refreshNote) {
        refreshNote.textContent = "Refresh failed. Try again.";
      }
    } finally {
      refreshButton.classList.remove("is-refreshing");
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener("click", refreshReports);
})();
