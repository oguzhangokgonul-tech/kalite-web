(() => {
  "use strict";

  const installButtons = Array.from(document.querySelectorAll("[data-pwa-install]"));
  const iosHelpItems = Array.from(document.querySelectorAll("[data-pwa-ios-help]"));
  const networkItems = Array.from(document.querySelectorAll("[data-pwa-network-status]"));
  const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const ios = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  let installPrompt = null;

  function setButtonsVisible(visible, label) {
    installButtons.forEach((button) => {
      button.hidden = !visible;
      if (label) {
        const text = button.querySelector("span");
        if (text) text.textContent = label;
      }
    });
  }

  function hideIosHelp() {
    iosHelpItems.forEach((item) => { item.hidden = true; });
  }

  function updateNetworkStatus() {
    const online = window.navigator.onLine;
    networkItems.forEach((item) => {
      item.classList.toggle("offline", !online);
      const icon = item.querySelector("i");
      const text = item.querySelector("span");
      if (icon) icon.className = online ? "bi bi-wifi" : "bi bi-wifi-off";
      if (text) text.textContent = online ? "Çevrimiçi" : "Çevrimdışı";
    });
  }

  if ("serviceWorker" in navigator && (window.isSecureContext || window.location.hostname === "localhost")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
        // PWA kurulumu başarısız olsa da normal web deneyimini etkileme.
      });
    });
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    setButtonsVisible(!standalone, "Uygulamayı Yükle");
  });

  installButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (installPrompt) {
        installPrompt.prompt();
        await installPrompt.userChoice;
        installPrompt = null;
        setButtonsVisible(false);
        return;
      }
      if (ios && !standalone) {
        iosHelpItems.forEach((item) => { item.hidden = !item.hidden; });
      }
    });
  });

  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    setButtonsVisible(false);
    hideIosHelp();
  });
  window.addEventListener("online", updateNetworkStatus);
  window.addEventListener("offline", updateNetworkStatus);

  if (ios && !standalone) setButtonsVisible(true, "Ana Ekrana Ekle");
  if (standalone) setButtonsVisible(false);
  updateNetworkStatus();
})();
