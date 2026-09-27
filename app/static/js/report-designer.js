(() => {
  "use strict";

  const sourceSelect = document.getElementById("reportSource");
  const columnsContainer = document.getElementById("reportColumns");
  const sourceDataElement = document.getElementById("reportSourcesData");
  const selectedColumnsElement = document.getElementById("reportSelectedColumns");
  if (!sourceSelect || !columnsContainer || !sourceDataElement) return;

  const sources = JSON.parse(sourceDataElement.textContent || "[]");
  const initialColumns = new Set(JSON.parse(selectedColumnsElement?.textContent || "[]"));
  let firstRender = true;

  function currentSource() {
    return sources.find((source) => source.key === sourceSelect.value);
  }

  function fillFieldSelect(select, headers) {
    const selected = select.dataset.selected || select.value;
    select.replaceChildren(new Option("Kolon seçin", ""));
    headers.forEach((header) => select.add(new Option(header, header)));
    if (headers.includes(selected)) select.value = selected;
  }

  function renderSourceFields() {
    const source = currentSource();
    const headers = source?.headers || [];
    columnsContainer.replaceChildren();
    if (!headers.length) {
      const empty = document.createElement("div");
      empty.className = "report-designer-empty";
      empty.textContent = "Önce veri kaynağı seçin.";
      columnsContainer.append(empty);
    } else {
      headers.forEach((header, index) => {
        const label = document.createElement("label");
        label.className = "report-option-check";
        const input = document.createElement("input");
        input.className = "form-check-input";
        input.type = "checkbox";
        input.name = "columns";
        input.value = header;
        input.checked = firstRender && initialColumns.size ? initialColumns.has(header) : index < 8;
        const text = document.createElement("span");
        text.textContent = header;
        label.append(input, text);
        columnsContainer.append(label);
      });
    }
    document.querySelectorAll(".report-field-select").forEach((select) => fillFieldSelect(select, headers));
    firstRender = false;
  }

  sourceSelect.addEventListener("change", renderSourceFields);
  renderSourceFields();
})();
