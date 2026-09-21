(() => {
  const form = document.getElementById("workflowDesigner");
  if (!form) return;
  const list = document.getElementById("workflowSteps");
  const template = document.getElementById("workflowStepTemplate");
  let dragging = null;

  function sync() {
    [...list.children].forEach((row, index) => {
      row.querySelector(".workflow-step-number").textContent = String(index + 1);
      row.querySelector(".workflow-step-summary").textContent = row.querySelector(".step-name").value || "Yeni adım";
      row.dataset.assignment = row.querySelector(".assignment-mode").value;
      row.dataset.type = row.querySelector(".step-type").value;
    });
  }
  function wire(row) {
    row.querySelector(".step-name").addEventListener("input", sync);
    row.querySelector(".assignment-mode").addEventListener("change", sync);
    row.querySelector(".step-type").addEventListener("change", sync);
    row.querySelector(".remove-step").addEventListener("click", () => { row.remove(); sync(); });
    row.querySelector(".move-step-up").addEventListener("click", () => { if (row.previousElementSibling) list.insertBefore(row, row.previousElementSibling); sync(); });
    row.querySelector(".move-step-down").addEventListener("click", () => { if (row.nextElementSibling) list.insertBefore(row.nextElementSibling, row); sync(); });
    row.addEventListener("dragstart", () => { dragging = row; row.classList.add("is-dragging"); });
    row.addEventListener("dragend", () => { row.classList.remove("is-dragging"); dragging = null; sync(); });
    row.addEventListener("dragover", event => {
      event.preventDefault();
      if (!dragging || dragging === row) return;
      const box = row.getBoundingClientRect();
      list.insertBefore(dragging, event.clientY < box.top + box.height / 2 ? row : row.nextElementSibling);
    });
  }
  [...list.children].forEach(wire);
  document.getElementById("addWorkflowStep").addEventListener("click", () => {
    const row = template.content.firstElementChild.cloneNode(true);
    list.appendChild(row); wire(row); sync(); row.querySelector(".step-name").focus();
  });
  form.addEventListener("submit", event => {
    if (!list.children.length) { event.preventDefault(); alert("En az bir iş akışı adımı ekleyin."); }
  });
  sync();
})();
