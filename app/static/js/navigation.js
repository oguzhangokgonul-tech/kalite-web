(() => {
  const sidebar = document.getElementById('dashboardSidebar');
  if (!sidebar) return;
  const root = document.documentElement;
  const main = document.querySelector('.dashboard-main');
  const modeButton = sidebar.querySelector('[data-nav-mode-toggle]');
  const mobileToggle = document.querySelector('[data-bs-toggle="offcanvas"][data-bs-target="#dashboardSidebar"]');
  const desktop = matchMedia('(min-width: 1200px) and (hover: hover) and (pointer: fine)');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const search = sidebar.querySelector('#vpNavSearch');
  const nav = sidebar.querySelector('.dashboard-sidebar-nav');
  const groups = [...nav.querySelectorAll('.dashboard-nav-group')];
  const links = [...sidebar.querySelectorAll('.dashboard-nav-item, .dashboard-subnav-item, .sidebar-quick-link, .dashboard-logout')];
  const tooltips = [];
  let mainAnimation;
  let searchState = null;
  let lastFocusedElement = document.activeElement;
  document.addEventListener('focusin', event => { lastFocusedElement = event.target; });
  const normalize = value => value.toLocaleLowerCase('tr-TR').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ı/g, 'i');

  links.forEach(link => {
    const label = link.querySelector('span:not(.assigned-count-badge):not(.sidebar-count-badge)')?.textContent.trim();
    if (!label) return;
    if (!link.hasAttribute('aria-label')) link.setAttribute('aria-label', label);
    if (link.matches('a') && link.classList.contains('active')) link.setAttribute('aria-current', 'page');
    if (window.bootstrap?.Tooltip && !link.classList.contains('dashboard-subnav-item')) {
      const tooltip = new bootstrap.Tooltip(link, { title: label, placement: 'right', container: 'body', trigger: 'hover focus', delay: { show: 150, hide: 0 }, customClass: 'vp-nav-tooltip' });
      tooltips.push(tooltip);
    }
  });

  function syncMode() {
    const compact = desktop.matches && root.dataset.navMode === 'compact';
    modeButton.setAttribute('aria-expanded', String(!compact));
    const label = compact ? modeButton.dataset.expandLabel : modeButton.dataset.collapseLabel;
    modeButton.setAttribute('aria-label', label);
    modeButton.title = label;
    tooltips.forEach(t => { t.hide(); compact ? t.enable() : t.disable(); });
  }

  function setMode(mode) {
    if (mode === 'compact' && search.value) { search.value = ''; filterMenu(); }
    mainAnimation?.cancel();
    const before = main.getBoundingClientRect().left;
    root.dataset.navMode = mode;
    try { localStorage.setItem('vp-nav-mode', mode); } catch (_) { /* Optional preference. */ }
    syncMode();
    // One layout change; only the content's transform is animated between positions.
    const delta = before - main.getBoundingClientRect().left;
    if (desktop.matches && !reducedMotion.matches && delta) {
      mainAnimation = main.animate([{ transform: `translateX(${delta}px)` }, { transform: 'translateX(0)' }], { duration: 180, easing: 'cubic-bezier(.2,.8,.2,1)' });
    }
  }
  modeButton.addEventListener('click', () => setMode(root.dataset.navMode === 'compact' ? 'expanded' : 'compact'));
  // Intercept before Bootstrap's document capture handler toggles the group.
  window.addEventListener('click', event => {
    const toggle = event.target.closest('.dashboard-nav-toggle');
    if (toggle && sidebar.contains(toggle) && desktop.matches && root.dataset.navMode === 'compact') {
      event.preventDefault();
      event.stopPropagation();
      setMode('expanded');
      const panel = document.querySelector(toggle.dataset.bsTarget);
      if (panel) bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false }).show();
    }
  }, true);
  sidebar.addEventListener('shown.bs.collapse', event => {
    if (!event.target.classList.contains('dashboard-subnav') || reducedMotion.matches) return;
    event.target.animate([{ opacity: 0, transform: 'translateY(-4px)' }, { opacity: 1, transform: 'none' }], { duration: 140, easing: 'ease-out' });
  });

  function filterMenu() {
    const query = normalize(search.value.trim());
    if (query && !searchState) searchState = new Map(groups.map(group => [group, group.querySelector('.dashboard-subnav').classList.contains('show')]));
    let matches = 0;
    [...nav.children].forEach(item => {
      if (item.classList.contains('vp-nav-empty')) return;
      if (item.classList.contains('dashboard-nav-group')) {
        const toggle = item.querySelector('.dashboard-nav-toggle');
        const panel = item.querySelector('.dashboard-subnav');
        const parentMatches = normalize(toggle.textContent).includes(query);
        const children = [...panel.querySelectorAll('a')];
        children.forEach(link => { link.hidden = !!query && !parentMatches && !normalize(link.textContent).includes(query); });
        const shown = !query || parentMatches || children.some(link => !link.hidden);
        item.hidden = !shown;
        const open = query ? shown : (searchState?.get(item) ?? panel.classList.contains('show'));
        panel.classList.toggle('show', open);
        panel.classList.remove('collapsing');
        panel.classList.add('collapse');
        panel.style.height = '';
        toggle.setAttribute('aria-expanded', String(open));
        if (shown) matches++;
      } else {
        item.hidden = !!query && !normalize(item.textContent).includes(query);
        if (!item.hidden) matches++;
      }
    });
    nav.querySelector('.vp-nav-empty').hidden = matches > 0;
    if (!query) searchState = null;
  }
  search.addEventListener('input', filterMenu);
  search.addEventListener('keydown', event => {
    if (event.key === 'Escape' && search.value) {
      event.stopPropagation(); search.value = ''; filterMenu();
    }
  });
  nav.addEventListener('scroll', () => tooltips.forEach(t => t.hide()), { passive: true });
  desktop.addEventListener('change', () => {
    mainAnimation?.cancel();
    // A breakpoint may hide the focused element before the media event arrives.
    const focusInSidebar = sidebar.contains(lastFocusedElement);
    if (desktop.matches) {
      bootstrap.Offcanvas.getInstance(sidebar)?.hide();
      if (root.dataset.navMode === 'compact' && search.value) { search.value = ''; filterMenu(); }
      if (focusInSidebar || lastFocusedElement === mobileToggle) modeButton.focus({ preventScroll: true });
    } else if (focusInSidebar && !sidebar.classList.contains('show')) {
      mobileToggle?.focus({ preventScroll: true });
    }
    syncMode();
  });
  syncMode();
  root.dataset.navigationReady = 'true';
})();
