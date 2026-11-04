(() => {
  const maxFileBytes = 8 * 1024 * 1024;
  const maxRequestBytes = 24 * 1024 * 1024;

  document.querySelectorAll("[data-calibration-scan]").forEach((form) => {
    const open = form.querySelector("[data-scan-open]");
    const firstInput = form.querySelector("[data-scan-capture]");
    const ready = form.querySelector("[data-scan-ready]");
    const preview = form.querySelector("[data-scan-preview]");
    const name = form.querySelector("[data-scan-name]");
    const submit = form.querySelector("[data-scan-submit]");
    const cancel = form.querySelector("[data-scan-cancel]");
    const pages = [];
    let activeInput = firstInput;
    let nextInputId = 0;

    function render() {
      preview.replaceChildren();
      pages.forEach((page, index) => {
        const card = document.createElement("div");
        card.className = "calibration-scan-page";
        const image = document.createElement("img");
        image.src = page.url;
        image.alt = `${index + 1}. sayfa önizlemesi`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn btn-light btn-sm calibration-scan-remove";
        remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
        remove.title = "Sayfayı kaldır";
        remove.setAttribute("aria-label", `${index + 1}. sayfayı kaldır`);
        remove.addEventListener("click", () => {
          URL.revokeObjectURL(page.url);
          page.input.remove();
          pages.splice(index, 1);
          render();
        });
        card.append(image, remove);
        preview.append(card);
      });
      ready.hidden = pages.length === 0;
      name.textContent = `${pages.length} sayfa seçildi`;
      open.setAttribute("aria-disabled", pages.length >= 10 ? "true" : "false");
      submit.disabled = pages.length === 0;
    }

    function addEmptyInput() {
      const input = firstInput.cloneNode(false);
      input.id = `${firstInput.id}-page-${++nextInputId}`;
      input.value = "";
      input.addEventListener("change", onCapture);
      form.insertBefore(input, ready);
      activeInput = input;
      open.htmlFor = input.id;
    }

    function onCapture(event) {
      const input = event.currentTarget;
      const file = input.files && input.files[0];
      if (!file) return;
      const totalBytes = pages.reduce((total, page) => total + page.file.size, file.size);
      if (file.size === 0 || file.size > maxFileBytes || totalBytes > maxRequestBytes) {
        input.setCustomValidity("Fotoğraf başına en fazla 8 MB, toplamda 24 MB yükleyebilirsiniz.");
      } else if (pages.length >= 10) {
        input.setCustomValidity("En fazla 10 sayfa ekleyebilirsiniz.");
      }
      if (input.validationMessage) {
        input.reportValidity();
        input.value = "";
        input.setCustomValidity("");
        return;
      }
      pages.push({ input, file, url: URL.createObjectURL(file) });
      addEmptyInput();
      render();
    }

    firstInput.addEventListener("change", onCapture);
    open.addEventListener("click", (event) => {
      if (pages.length >= 10) event.preventDefault();
    });
    open.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (pages.length < 10) activeInput.click();
      }
    });
    cancel.addEventListener("click", () => {
      pages.forEach((page) => {
        URL.revokeObjectURL(page.url);
        page.input.remove();
      });
      pages.length = 0;
      activeInput.remove();
      addEmptyInput();
      render();
    });
    form.addEventListener("submit", (event) => {
      if (!pages.length) {
        event.preventDefault();
        return;
      }
      submit.disabled = true;
      submit.textContent = "Yükleniyor...";
    });
    window.addEventListener("pagehide", () => pages.forEach((page) => URL.revokeObjectURL(page.url)));
  });
})();
