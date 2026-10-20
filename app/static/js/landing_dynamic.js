(() => {
  'use strict';
  const root = document.querySelector('[data-dynamic-landing]');
  if (!root) return;
  const header = root.querySelector('.vp-dynamic-header');
  const visual = root.querySelector('.vp-story-visual');
  const triggers = [...root.querySelectorAll('[data-scene-trigger]')];
  const scenes = [...root.querySelectorAll('[data-scene]')];
  const progress = root.querySelector('[data-scroll-progress]');
  const glow = root.querySelector('[data-cursor-glow]');
  const inline = matchMedia('(max-width: 1100px)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const pointer = matchMedia('(pointer: fine)');
  let centers = [], pageHeight = 1, viewportHeight = innerHeight, headerSpace = 0;
  let active = '', compact = false, frame = 0, dirty = true, interacted = false;
  let pointerDirty = false, mouseX = -999, mouseY = -999;

  function updateLayout() {
    root.classList.toggle('is-inline-story', inline.matches);
    scenes.forEach((scene, index) => {
      if (inline.matches) triggers[index].after(scene);
      else visual.append(scene);
      scene.setAttribute('aria-hidden', String(!inline.matches && scene.dataset.scene !== active));
    });
    dirty = true;
    schedule();
  }

  function measure() {
    viewportHeight = innerHeight;
    headerSpace = inline.matches ? 0 : header.offsetHeight + 38;
    const y = scrollY;
    // Layout is read only on resize/content changes, never on ordinary scroll frames.
    centers = triggers.map(trigger => {
      const rect = trigger.getBoundingClientRect();
      return y + rect.top + rect.height / 2;
    });
    pageHeight = Math.max(1, document.documentElement.scrollHeight - viewportHeight);
    const visualHeight = inline.matches ? 0 : visual.offsetHeight;
    const stickyTop = Math.max(headerSpace, (viewportHeight + headerSpace - visualHeight) / 2);
    root.style.setProperty('--landing-anchor-offset', `${headerSpace || 24}px`);
    root.style.setProperty('--landing-story-top', `${stickyTop}px`);
    root.style.setProperty('--landing-scene-height', `${visualHeight}px`);
    dirty = false;
  }

  function activate(key) {
    if (active === key) return;
    active = key;
    root.dataset.activeScene = key;
    triggers.forEach(trigger => trigger.classList.toggle('is-active', trigger.dataset.sceneTrigger === key));
    scenes.forEach(scene => {
      const selected = scene.dataset.scene === key;
      scene.classList.toggle('is-active', selected);
      scene.setAttribute('aria-hidden', String(!inline.matches && !selected));
    });
  }

  function render() {
    frame = 0;
    if (document.hidden) return;
    if (dirty) measure();
    const y = scrollY;
    const line = y + (viewportHeight + headerSpace) / 2;
    let nearest = 0;
    centers.forEach((center, index) => {
      if (Math.abs(center - line) < Math.abs(centers[nearest] - line)) nearest = index;
    });
    if (triggers[nearest]) activate(triggers[nearest].dataset.sceneTrigger);
    if (progress) progress.style.transform = `scaleX(${Math.min(1, Math.max(0, y / pageHeight))})`;
    const nextCompact = !inline.matches && (compact ? y > 48 : y > 96);
    if (compact !== nextCompact) {
      compact = nextCompact;
      header.classList.toggle('is-compact', compact);
    }
    if (pointerDirty && glow && pointer.matches && !reduced.matches) {
      glow.style.setProperty('--x', `${mouseX}px`);
      glow.style.setProperty('--y', `${mouseY}px`);
      pointerDirty = false;
    }
  }
  function schedule() {
    if (!frame && !document.hidden) frame = requestAnimationFrame(render);
  }
  function invalidate() { dirty = true; schedule(); }

  root.classList.add('is-enhanced');
  updateLayout();
  measure();
  inline.addEventListener('change', updateLayout);
  window.addEventListener('scroll', schedule, {passive: true});
  window.addEventListener('resize', invalidate, {passive: true});
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(invalidate);
    [root, header, visual, ...triggers, ...scenes].forEach(el => observer.observe(el));
  }
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => entry.target.classList.toggle('vp-motion-paused', !entry.isIntersecting));
    }, {rootMargin: '100px'});
    root.querySelectorAll('.vp-dynamic-hero, .vp-dynamic-strip, .vp-scroll-story, .vp-scene').forEach(el => observer.observe(el));
  }
  document.addEventListener('visibilitychange', () => {
    root.classList.toggle('vp-page-paused', document.hidden);
    if (document.hidden && frame) { cancelAnimationFrame(frame); frame = 0; }
    if (!document.hidden) invalidate();
  });
  function movePointer(event) {
    mouseX = event.clientX;
    mouseY = event.clientY;
    pointerDirty = true;
    schedule();
  }
  function syncPointer() {
    window.removeEventListener('pointermove', movePointer);
    const enabled = pointer.matches && !reduced.matches;
    if (glow) glow.hidden = !enabled;
    if (enabled) window.addEventListener('pointermove', movePointer, {passive: true});
  }
  syncPointer();
  pointer.addEventListener('change', syncPointer);
  reduced.addEventListener('change', syncPointer);

  // Do not replace wheel/touch scrolling or run a fixed-rate interpolation timer.
  root.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (!link || event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = document.getElementById(link.hash.slice(1));
    if (!target) return;
    event.preventDefault();
    interacted = true;
    if (dirty) measure();
    if (location.hash !== link.hash) history.pushState(history.state, '', link.hash);
    target.setAttribute('tabindex', '-1');
    target.focus({preventScroll: true});
    target.scrollIntoView({block: 'start', behavior: reduced.matches ? 'instant' : 'smooth'});
  });
  function alignHash() {
    const target = [root, ...root.querySelectorAll('[id]')].find(el => `#${el.id}` === location.hash);
    if (!target) return;
    measure();
    target.scrollIntoView({block: 'start', behavior: 'instant'});
    schedule();
  }
  ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach(name => {
    window.addEventListener(name, () => { interacted = true; }, {once: true, passive: true});
  });
  window.addEventListener('hashchange', () => requestAnimationFrame(alignHash));
  window.addEventListener('load', async () => {
    if (document.fonts) await document.fonts.ready;
    invalidate();
    if (!interacted) requestAnimationFrame(alignHash);
  }, {once: true});
})();
