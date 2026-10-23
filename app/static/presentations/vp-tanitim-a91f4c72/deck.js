(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const counter = document.getElementById('slide-counter');
  const progress = document.getElementById('progress-fill');
  const chapter = document.getElementById('chapter-name');
  const previous = document.getElementById('previous-button');
  const next = document.getElementById('next-button');
  const outline = document.getElementById('outline-dialog');
  const outlineNav = document.getElementById('outline-nav');
  const imageDialog = document.getElementById('image-dialog');
  const expandedImage = document.getElementById('image-expanded');
  let active = 0;

  outlineNav.replaceChildren(...slides.map((slide, index) => {
    const link = document.createElement('a');
    const number = document.createElement('span');
    number.textContent = String(index + 1).padStart(2, '0');
    link.href = `#${slide.id}`;
    link.append(number, document.createTextNode(slide.dataset.title));
    link.addEventListener('click', event => {
      event.preventDefault();
      outline.close();
      history.replaceState(null, '', `#${slide.id}`);
      goTo(index);
    });
    return link;
  }));

  function setActive(index) {
    active = Math.max(0, Math.min(slides.length - 1, index));
    slides.forEach((slide, slideIndex) => slide.classList.toggle('is-visible', slideIndex === active));
    counter.textContent = `${String(active + 1).padStart(2, '0')} / ${String(slides.length).padStart(2, '0')}`;
    progress.style.transform = `scaleX(${(active + 1) / slides.length})`;
    chapter.textContent = slides[active].dataset.title;
    previous.disabled = active === 0;
    next.disabled = active === slides.length - 1;
    outlineNav.querySelectorAll('a').forEach((link, linkIndex) => {
      if (linkIndex === active) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  function goTo(index) {
    const nextIndex = Math.max(0, Math.min(slides.length - 1, index));
    slides[nextIndex].scrollIntoView({ behavior: 'instant', block: 'start' });
    setActive(nextIndex);
  }

  previous.addEventListener('click', () => goTo(active - 1));
  next.addEventListener('click', () => goTo(active + 1));
  document.getElementById('outline-button').addEventListener('click', () => outline.showModal());
  document.getElementById('outline-close').addEventListener('click', () => outline.close());
  document.getElementById('image-close').addEventListener('click', () => imageDialog.close());
  [outline, imageDialog].forEach(dialog => dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  }));

  document.getElementById('fullscreen-button').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      // Browsers that disallow fullscreen leave the presentation usable.
    }
  });

  document.addEventListener('keydown', event => {
    if (outline.open || imageDialog.open || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable]')) return;
    if (event.key === ' ' && event.target instanceof Element && event.target.closest('a, button, [role="button"]')) return;
    if (['ArrowRight', 'ArrowDown', 'PageDown'].includes(event.key) || (event.key === ' ' && !event.shiftKey)) {
      event.preventDefault();
      goTo(active + 1);
    } else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key) || (event.key === ' ' && event.shiftKey)) {
      event.preventDefault();
      goTo(active - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      goTo(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      goTo(slides.length - 1);
    }
  });

  let touchStart = null;
  document.addEventListener('touchstart', event => {
    if (event.touches.length === 1) touchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  }, { passive: true });
  document.addEventListener('touchend', event => {
    if (!touchStart || outline.open || imageDialog.open || event.changedTouches.length !== 1) return;
    const dx = event.changedTouches[0].clientX - touchStart.x;
    const dy = event.changedTouches[0].clientY - touchStart.y;
    if (Math.abs(dx) > 90 && Math.abs(dx) > Math.abs(dy) * 1.7) goTo(active + (dx < 0 ? 1 : -1));
    touchStart = null;
  }, { passive: true });

  document.querySelectorAll('figure.screen, figure.phone-screen').forEach(figure => {
    const image = figure.querySelector('img');
    const caption = figure.querySelector('figcaption');
    const zoomIcon = document.createElement('i');
    zoomIcon.className = 'bi bi-arrows-angle-expand zoom-icon';
    zoomIcon.setAttribute('aria-hidden', 'true');
    caption?.append(zoomIcon);
    figure.tabIndex = 0;
    figure.setAttribute('role', 'button');
    figure.setAttribute('aria-label', `Görseli büyüt: ${image.alt}`);
    figure.title = 'Görseli büyüt';
    const openImage = () => {
      expandedImage.src = image.src;
      expandedImage.alt = image.alt;
      document.getElementById('image-title').textContent = figure.querySelector('figcaption')?.textContent || image.alt;
      imageDialog.showModal();
    };
    figure.addEventListener('click', openImage);
    figure.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openImage();
      }
    });
  });

  const observer = new IntersectionObserver(entries => {
    const mostVisible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (mostVisible) setActive(slides.indexOf(mostVisible.target));
  }, { threshold: [0.15, 0.35, 0.6, 0.8] });
  slides.forEach(slide => observer.observe(slide));
  setActive(Math.max(0, slides.findIndex(slide => slide.id === location.hash.slice(1))));
  document.body.classList.add('js-ready');
})();
