document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('personalPermissionsForm');
  const search = document.getElementById('permissionSearch');
  const count = document.getElementById('permissionChangeCount');
  if (!form || !search || !count) return;
  const rows = [...form.querySelectorAll('.personal-permission-row')];
  const valueOf = (control) => control.type === 'checkbox' ? control.checked : control.value;
  const original = new Map(rows.map((row) => {
    const control = row.querySelector('select, input[type="checkbox"]');
    return [control, valueOf(control)];
  }));
  const updateCount = () => {
    const changed = [...original].filter(([control, value]) => valueOf(control) !== value).length;
    count.textContent = changed ? `${changed} yetki değiştirildi` : 'Değişiklik yok';
  };
  form.addEventListener('change', updateCount);
  search.addEventListener('input', () => {
    const term = search.value.trim().toLocaleLowerCase('tr');
    for (const group of form.querySelectorAll('.personal-permission-group')) {
      let visible = 0;
      for (const row of group.querySelectorAll('.personal-permission-row')) {
        const match = row.dataset.permissionSearch.toLocaleLowerCase('tr').includes(term);
        row.hidden = !match;
        if (match) visible += 1;
      }
      group.hidden = visible === 0;
      if (term && visible) group.open = true;
    }
  });
});
