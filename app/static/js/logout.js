(() => {
  "use strict";

  document.querySelectorAll("form[data-logout-form]").forEach((form) => {
    let submitting = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submitting) return;
      submitting = true;

      const button = form.querySelector('button[type="submit"]');
      const refreshUrl = form.dataset.csrfRefreshUrl;
      const loginUrl = form.dataset.loginUrl || "/login";
      if (button) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
      }

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch(refreshUrl, {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (response.status === 401) {
          window.location.assign(loginUrl);
          return;
        }
        if (!response.ok) throw new Error("CSRF token refresh failed");

        const payload = await response.json();
        if (!payload.csrf_token) throw new Error("CSRF token missing");
        const tokenInput = form.querySelector('input[name="csrf_token"]');
        if (!tokenInput) throw new Error("CSRF input missing");
        tokenInput.value = payload.csrf_token;
        HTMLFormElement.prototype.submit.call(form);
      } catch (error) {
        submitting = false;
        if (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        }
        window.alert("Çıkış tamamlanamadı. Bağlantınızı kontrol edip tekrar deneyin.");
      } finally {
        clearTimeout(timeout);
      }
    });
  });
})();
