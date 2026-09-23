(() => {
  const list = document.getElementById("fieldList");
  const template = document.getElementById("fieldTemplate");
  const addButton = document.getElementById("addField");
  if (!list || !template || !addButton) return;

  const makeKey = () => {
    if (window.crypto?.getRandomValues) {
      const values = new Uint32Array(2);
      window.crypto.getRandomValues(values);
      return `field_${[...values].map(value => value.toString(16)).join("")}`;
    }
    return `field_${Date.now().toString(16)}${Math.random().toString(16).slice(2, 8)}`;
  };

  const toggleRowSettings = row => {
    const type = row.querySelector(".field-type").value;
    row.dataset.type = type;
    row.querySelector(".field-options-wrap").classList.toggle("d-none", !["single_choice", "multiple_choice"].includes(type));
    row.querySelectorAll(".validation-text").forEach(node => node.classList.toggle("d-none", !["short_text", "long_text", "email", "phone"].includes(type)));
    row.querySelectorAll(".validation-number").forEach(node => node.classList.toggle("d-none", !["number", "rating"].includes(type)));
  };

  const toggleCondition = row => {
    const source = row.querySelector(".condition-source");
    const operator = row.querySelector('[name="field_condition_operator"]');
    row.querySelectorAll(".condition-settings").forEach(node => node.classList.toggle("d-none", !source.value));
    row.querySelector(".condition-value").closest(".condition-settings").classList.toggle("d-none", !source.value || operator.value === "not_empty");
  };

  const sync = () => {
    const rows = [...list.querySelectorAll(".dynamic-field-row")];
    rows.forEach((row, index) => {
      const keyInput = row.querySelector('[name="field_key"]');
      if (!keyInput.value) keyInput.value = makeKey();
      row.dataset.fieldKey = keyInput.value;
      const required = row.querySelector(".required-box");
      required.name = "field_required";
      required.value = String(index);
      required.id = `field-required-${index}`;
      required.nextElementSibling.htmlFor = required.id;
      row.querySelector(".dynamic-field-order").textContent = String(index + 1);
      row.querySelector(".dynamic-field-summary").textContent = row.querySelector(".field-label").value.trim() || "Yeni alan";

      const source = row.querySelector(".condition-source");
      const selected = source.value || source.dataset.selected || "";
      source.innerHTML = '<option value="">Her zaman göster</option>';
      rows.slice(0, index).forEach(previous => {
        const option = document.createElement("option");
        option.value = previous.querySelector('[name="field_key"]').value;
        option.textContent = previous.querySelector(".field-label").value.trim() || `Alan ${rows.indexOf(previous) + 1}`;
        option.selected = option.value === selected;
        source.appendChild(option);
      });
      source.dataset.selected = source.value;
      toggleRowSettings(row);
      toggleCondition(row);
    });
  };

  const wire = row => {
    row.querySelector(".field-type").addEventListener("change", () => { toggleRowSettings(row); sync(); });
    row.querySelector(".field-label").addEventListener("input", sync);
    row.querySelector(".condition-source").addEventListener("change", event => { event.currentTarget.dataset.selected = event.currentTarget.value; toggleCondition(row); });
    row.querySelector('[name="field_condition_operator"]').addEventListener("change", () => toggleCondition(row));
    row.querySelector(".remove-field").addEventListener("click", () => { row.remove(); sync(); });
    row.querySelector(".move-up").addEventListener("click", () => { if (row.previousElementSibling) list.insertBefore(row, row.previousElementSibling); sync(); });
    row.querySelector(".move-down").addEventListener("click", () => { if (row.nextElementSibling) list.insertBefore(row.nextElementSibling, row); sync(); });
    row.addEventListener("dragstart", event => { row.classList.add("is-dragging"); event.dataTransfer.effectAllowed = "move"; });
    row.addEventListener("dragend", () => { row.classList.remove("is-dragging"); sync(); });
    row.addEventListener("dragover", event => {
      event.preventDefault();
      const dragging = list.querySelector(".is-dragging");
      if (!dragging || dragging === row) return;
      const after = event.clientY > row.getBoundingClientRect().top + row.offsetHeight / 2;
      list.insertBefore(dragging, after ? row.nextElementSibling : row);
    });
  };

  [...list.querySelectorAll(".dynamic-field-row")].forEach(wire);
  addButton.addEventListener("click", () => {
    const row = template.content.firstElementChild.cloneNode(true);
    list.appendChild(row);
    wire(row);
    sync();
    row.querySelector(".field-label").focus();
  });
  if (!list.children.length) addButton.click();
  sync();
})();
