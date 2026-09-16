(() => {
  document.querySelectorAll('i.bi').forEach(icon => icon.setAttribute('aria-hidden', 'true'));
  const content = document.getElementById('dashboardMainContent');
  if (!content) return;
  const phone = window.matchMedia('(max-width: 767.98px)');
  const tables = new Map();
  const generatedLabels = new WeakMap();
  let preference = null;
  try { preference = sessionStorage.getItem('vp-list-view'); } catch (_) { /* Storage may be disabled. */ }
  if (!['records', 'table'].includes(preference)) preference = null;

  function resetTable(table, scroll = false) {
    const state = tables.get(table);
    if (state) {
      state.controls.remove();
      state.wrapper.classList.remove('vp-records-active');
      tables.delete(table);
    }
    table.classList.remove('vp-responsive-table');
    table.classList.toggle('vp-scroll-table', scroll);
    if (scroll) table.parentElement.classList.add('vp-table-viewport');
    table.querySelectorAll('.vp-record-row, .vp-record-detail').forEach(row => {
      row.classList.remove('vp-record-row', 'vp-record-detail');
    });
  }

  function labelRows(table, headings) {
    for (const body of table.tBodies) {
      for (const row of body.rows) {
        const cells = [...row.cells];
        row.classList.remove('vp-record-row', 'vp-record-detail');
        if (cells.length === headings.length && cells.every(cell => cell.colSpan === 1)) {
          row.classList.add('vp-record-row');
          cells.forEach((cell, index) => {
            if (!cell.dataset.label || generatedLabels.get(cell) === cell.dataset.label) {
              cell.dataset.label = headings[index];
              generatedLabels.set(cell, headings[index]);
            }
          });
        } else if (cells.length === 1 && cells[0].colSpan === headings.length) {
          row.classList.add('vp-record-detail');
        }
      }
    }
  }

  function prepareTable(table) {
    const wrapper = table.parentElement;
    if (table.closest('table table') || table.dataset.responsive === 'scroll' ||
        !wrapper.matches('.table-responsive, .dashboard-table-wrapper, .company-table-wrapper')) {
      resetTable(table);
      return;
    }
    const header = table.tHead;
    if (!header || header.rows.length !== 1) { resetTable(table, true); return; }
    const columns = [...header.rows[0].cells];
    if (columns.length < 2 || columns.some(cell => cell.colSpan !== 1 || cell.rowSpan !== 1)) {
      resetTable(table, true); return;
    }
    if ([...table.tBodies].some(body => [...body.rows].some(row => {
      const cells = [...row.cells];
      const normal = cells.length === columns.length && cells.every(cell => cell.colSpan === 1 && cell.rowSpan === 1);
      const detail = cells.length === 1 && cells[0].colSpan === columns.length && cells[0].rowSpan === 1;
      return !normal && !detail;
    }))) { resetTable(table, true); return; }
    const headings = columns.map(cell => cell.textContent.trim().replace(/\s+/g, ' '));
    labelRows(table, headings);
    table.classList.add('vp-responsive-table');
    table.classList.remove('vp-scroll-table');
    columns.forEach(cell => {
      cell.classList.toggle('vp-column-control', !!cell.querySelector('button, a, input, select'));
    });
    const previous = tables.get(table);
    if (previous?.wrapper === wrapper) return;
    if (previous) resetTable(table);
    table.classList.add('vp-responsive-table');
    labelRows(table, headings);
    wrapper.classList.add('vp-table-viewport');
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', 'Kayıt listesi');
    const controls = document.createElement('div');
    controls.className = 'vp-list-view-controls';
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', 'Liste görünümü');
    const state = { wrapper, controls, buttons: [] };
    for (const [mode, icon, label] of [
      ['records', 'bi-view-stacked', 'Liste görünümü'],
      ['table', 'bi-table', 'Tablo görünümü'],
    ]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-outline-secondary btn-icon';
      button.title = label;
      button.setAttribute('aria-label', label);
      const symbol = document.createElement('i');
      symbol.className = `bi ${icon}`;
      symbol.setAttribute('aria-hidden', 'true');
      button.append(symbol);
      button.addEventListener('click', () => {
        preference = mode;
        try { sessionStorage.setItem('vp-list-view', mode); } catch (_) { /* Optional preference only. */ }
        tables.forEach(updateView);
      });
      state.buttons.push({ mode, button });
      controls.append(button);
    }
    wrapper.before(controls);
    tables.set(table, state);
    table.setAttribute('role', 'table');
    [...table.rows].forEach(row => {
      row.setAttribute('role', 'row');
      [...row.cells].forEach(cell => cell.setAttribute('role', cell.tagName === 'TH' ? 'columnheader' : 'cell'));
    });
    updateView(state);
  }

  function updateView(state) {
    const mode = preference || (phone.matches ? 'records' : 'table');
    state.wrapper.classList.toggle('vp-records-active', mode === 'records');
    state.buttons.forEach(({ mode: value, button }) => {
      button.setAttribute('aria-pressed', String(value === mode));
    });
  }

  function prepare(root) {
    root.querySelectorAll('table').forEach(prepareTable);
    root.querySelectorAll('button[title], a[title]').forEach(control => {
      if (!control.getAttribute('aria-label') && !control.textContent.trim()) {
        control.setAttribute('aria-label', control.title);
      }
    });
  }

  prepare(content);
  content.dataset.responsiveReady = 'true';
  phone.addEventListener('change', () => tables.forEach(updateView));
  // Reuse original cells and controls so module listeners and form values survive.
  const pending = new Set();
  let scheduled = false;
  new MutationObserver(records => {
    for (const record of records) {
      const target = record.target instanceof Element ? record.target : record.target.parentElement;
      const affected = target?.closest('table');
      if (affected) pending.add(affected);
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        const table = node.closest('table');
        if (table) pending.add(table);
        if (node.matches('table')) pending.add(node);
        node.querySelectorAll('table').forEach(table => pending.add(table));
      }
    }
    tables.forEach((_, table) => { if (!table.isConnected) resetTable(table); });
    if (!pending.size || scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      pending.forEach(table => {
        if (table.isConnected) prepareTable(table);
      });
      pending.clear();
    });
  }).observe(content, { childList: true, subtree: true, characterData: true,
                       attributes: true, attributeFilter: ['colspan', 'rowspan'] });
})();
