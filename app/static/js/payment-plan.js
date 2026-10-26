(() => {
  const count = document.getElementById('payment-installment-count');
  const rows = document.getElementById('payment-installment-rows');
  const total = document.getElementById('payment-amount');
  const split = document.getElementById('payment-even-split');
  if (!count || !rows || !total || !split) return;

  function resize() {
    const wanted = Math.max(1, Math.min(24, Number.parseInt(count.value, 10) || 1));
    count.value = wanted;
    while (rows.children.length > wanted) rows.lastElementChild.remove();
    while (rows.children.length < wanted) {
      const index = rows.children.length + 1;
      const row = document.createElement('div');
      row.className = 'payment-plan-row';
      row.innerHTML = `<span class="payment-plan-number">${index}. taksit</span><div><label for="payment-date-${index}">Tarih</label><input class="form-control" id="payment-date-${index}" name="installment_due_date" type="date" required></div><div><label for="payment-part-${index}">Tutar</label><input class="form-control" id="payment-part-${index}" name="installment_amount" inputmode="decimal" required></div>`;
      rows.append(row);
    }
  }

  function distribute() {
    resize();
    const cents = Math.round(Number(total.value.replace(',', '.')) * 100);
    if (!Number.isFinite(cents) || cents < rows.children.length) return;
    const base = Math.floor(cents / rows.children.length);
    rows.querySelectorAll('[name="installment_amount"]').forEach((field, index) => {
      field.value = ((base + (index === rows.children.length - 1 ? cents - base * rows.children.length : 0)) / 100).toFixed(2);
    });
  }

  count.addEventListener('change', resize);
  split.addEventListener('click', distribute);
  total.addEventListener('input', () => {
    const fields = rows.querySelectorAll('[name="installment_amount"]');
    if (fields.length === 1) fields[0].value = total.value;
  });
})();
