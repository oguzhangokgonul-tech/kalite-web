(() => {
  const form = document.querySelector("[data-calibration-scan]");
  if (!form) return;
  const capture = form.querySelector("[data-scan-capture]");
  const pages = form.querySelector("[data-scan-pages]");
  const preview = form.querySelector("[data-scan-preview]");
  const submit = form.querySelector("[data-scan-submit]");
  let selected = [];
  let previewUrls = [];
  const maxRequestBytes = 24 * 1024 * 1024;

  function render() {
    previewUrls.forEach((url) => URL.revokeObjectURL(url));
    previewUrls = [];
    preview.replaceChildren();
    const transfer = new DataTransfer();
    selected.forEach((file, index) => {
      transfer.items.add(file);
      const card = document.createElement("div");
      card.className = "calibration-scan-page";
      const image = document.createElement("img");
      const url = URL.createObjectURL(file);
      previewUrls.push(url);
      image.src = url;
      image.alt = `${index + 1}. sayfa önizlemesi`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-outline-danger btn-sm";
      remove.textContent = "Kaldır";
      remove.setAttribute("aria-label", `${index + 1}. sayfayı kaldır`);
      remove.addEventListener("click", () => {
        selected.splice(index, 1);
        render();
      });
      card.append(image, remove);
      preview.append(card);
    });
    pages.files = transfer.files;
    submit.disabled = selected.length === 0;
  }

  capture.addEventListener("change", () => {
    const additions = Array.from(capture.files || []);
    if (additions.some((file) => file.size > 8 * 1024 * 1024) ||
        selected.concat(additions).reduce((sum, file) => sum + file.size, 0) > maxRequestBytes) {
      capture.setCustomValidity("Fotoğraf başına en fazla 8 MB, toplamda 24 MB yükleyebilirsiniz.");
      capture.reportValidity();
      capture.value = "";
      return;
    }
    if (selected.length + additions.length > 10) {
      capture.setCustomValidity("En fazla 10 sayfa ekleyebilirsiniz.");
      capture.reportValidity();
      capture.value = "";
      return;
    }
    capture.setCustomValidity("");
    selected.push(...additions);
    capture.value = "";
    render();
  });
  form.addEventListener("submit", (event) => {
    if (!selected.length) event.preventDefault();
  });
  window.addEventListener("pagehide", () => previewUrls.forEach((url) => URL.revokeObjectURL(url)));
})();
