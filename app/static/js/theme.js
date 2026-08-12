(function () {
  var THEME_STORAGE_KEY = "baluc-theme";
  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");
  var label = document.getElementById("theme-toggle-label");

  function getActiveTheme() {
    var current = root.getAttribute("data-theme");
    return current === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_STORAGE_KEY, theme);

    if (label) {
      label.textContent = theme === "dark" ? "Light" : "Dark";
    }

    if (toggle) {
      toggle.setAttribute("aria-pressed", String(theme === "dark"));
      toggle.setAttribute("title", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    }
  }

  if (!toggle) {
    return;
  }

  applyTheme(getActiveTheme());

  toggle.addEventListener("click", function () {
    var nextTheme = getActiveTheme() === "dark" ? "light" : "dark";
    applyTheme(nextTheme);
  });
})();
