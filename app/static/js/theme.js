(() => {
  'use strict';
  const root = document.documentElement;
  const key = root.dataset.themeKey;
  const valid = value => value === 'dark' || value === 'light';
  const read = () => {
    try { return key ? localStorage.getItem(key) : null; } catch (_) { return null; }
  };
  let lightThemeColor;
  function apply(value) {
    const theme = valid(value) ? value : 'light';
    root.dataset.bsTheme = theme;
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.hidden = false;
      button.setAttribute('aria-pressed', String(theme === 'dark'));
      button.title = theme === 'dark' ? button.dataset.lightLabel : button.dataset.darkLabel;
      const icon = button.querySelector('[data-theme-icon]');
      if (icon) icon.className = theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon';
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      if (lightThemeColor === undefined) lightThemeColor = meta.content;
      meta.content = theme === 'dark' ? '#16181c' : lightThemeColor;
    }
  }
  // Execute before stylesheets to avoid a light flash for a saved dark preference.
  apply(read());
  document.addEventListener('DOMContentLoaded', () => {
    apply(root.dataset.bsTheme);
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', () => {
        const theme = root.dataset.bsTheme === 'dark' ? 'light' : 'dark';
        apply(theme);
        try { if (key) localStorage.setItem(key, theme); } catch (_) { /* Storage may be disabled. */ }
        document.dispatchEvent(new CustomEvent('vp:themechange', {detail: {theme}}));
      });
    });
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) apply(read());
  });
  window.addEventListener('pageshow', event => { if (event.persisted) apply(read()); });
})();
