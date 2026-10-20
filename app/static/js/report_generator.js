(function () {
  const startDateInput = document.getElementById("start_date");
  const endDateInput = document.getElementById("end_date");

  function syncDateRange() {
    if (!startDateInput || !endDateInput) {
      return;
    }

    const startValue = String(startDateInput.value || "").trim();
    endDateInput.min = startValue;

    if (endDateInput.value && startValue && endDateInput.value < startValue) {
      endDateInput.value = startValue;
    }

    if (endDateInput.value && startValue && endDateInput.value < startValue) {
      endDateInput.setCustomValidity("End Date must be greater than or equal to Start Date.");
    } else {
      endDateInput.setCustomValidity("");
    }
  }

  if (startDateInput && endDateInput) {
    syncDateRange();
    startDateInput.addEventListener("change", syncDateRange);
    endDateInput.addEventListener("change", syncDateRange);
    endDateInput.addEventListener("input", syncDateRange);
  }

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
    const actions = report.download_url && report.view_url
      ? '<a class="view-report" href="' + esc(report.view_url) + '">View Report</a>' +
        (report.reportset_url ? '<a class="view-report" href="' + esc(report.reportset_url) + '">ReportSet</a>' : "") +
        '<a class="download" href="' + esc(report.download_url) + '">CSV</a>'
      : '<span class="job-meta dash">-</span>';
    const error = report.error ? '<p class="job-error">' + esc(report.error) + "</p>" : "";

    return (
      '<div class="job job-row">' +
      '<p class="job-name">Print Report</p>' +
      '<p class="job-meta range">' + esc(report.start_date) + " to " + esc(report.end_date) + "</p>" +
      '<p class="job-meta requested">' + esc(report.requested_at) + "</p>" +
      '<span class="badge ' + statusClass + '">' + status + "</span>" +
      actions +
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
