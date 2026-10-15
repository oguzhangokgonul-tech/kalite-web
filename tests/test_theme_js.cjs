'use strict';

const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../app/static/js/theme.js'), 'utf8');
const KEY = 'vp-theme:11:22';
const LIGHT_COLOR = '#1248aa';

function eventTarget() {
  const listeners = new Map();
  return {
    addEventListener(type, listener) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(listener);
    },
    dispatchEvent(event) {
      for (const listener of listeners.get(event.type) || []) listener(event);
      return true;
    },
  };
}

function boot(options = {}) {
  const key = Object.hasOwn(options, 'key') ? options.key : KEY;
  const values = new Map(options.entries || []);
  if (Object.hasOwn(options, 'saved')) values.set(key, options.saved);
  const reads = [];
  const writes = [];
  const network = [];
  const changes = [];
  const root = { dataset: { bsTheme: 'light' } };
  if (key !== undefined) root.dataset.themeKey = key;
  const icon = { className: 'bi bi-moon' };
  const attributes = new Map([['aria-pressed', 'false'], ['aria-label', 'Dark theme']]);
  const button = Object.assign(eventTarget(), {
    hidden: true,
    dataset: { lightLabel: 'Switch to light', darkLabel: 'Switch to dark' },
    title: 'Switch to dark',
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.get(name) ?? null; },
    querySelector(selector) {
      assert.equal(selector, '[data-theme-icon]');
      return options.noIcon ? null : icon;
    },
  });
  let ready = false;
  const meta = { content: options.color || LIGHT_COLOR };
  const document = Object.assign(eventTarget(), {
    documentElement: root,
    querySelectorAll(selector) {
      assert.equal(selector, '[data-theme-toggle]');
      return ready && !options.noButton ? [button] : [];
    },
    querySelector(selector) {
      assert.equal(selector, 'meta[name="theme-color"]');
      return options.noMeta ? null : meta;
    },
  });
  document.addEventListener('vp:themechange', event => changes.push(event.detail.theme));
  const storage = {
    getItem(name) {
      reads.push(name);
      if (options.readThrows) throw new Error('Storage read blocked');
      return values.get(name) ?? null;
    },
    setItem(name, value) {
      writes.push([name, value]);
      if (options.writeThrows) throw new Error('Storage quota exceeded');
      values.set(name, String(value));
    },
  };
  function forbiddenNetwork(...args) {
    network.push(args);
    throw new Error('Theme must not make network requests');
  }
  const window = eventTarget();
  const globals = {
    window,
    document,
    CustomEvent: class CustomEvent {
      constructor(type, options = {}) { this.type = type; this.detail = options.detail; }
    },
    fetch: forbiddenNetwork,
    XMLHttpRequest: forbiddenNetwork,
    WebSocket: forbiddenNetwork,
    EventSource: forbiddenNetwork,
    Image: forbiddenNetwork,
    navigator: { sendBeacon: forbiddenNetwork },
    matchMedia: () => ({ matches: true }),
  };
  Object.defineProperty(globals, 'localStorage', {
    get() {
      if (options.storageThrows) throw new Error('Storage access denied');
      return storage;
    },
  });
  for (const name of Object.keys(globals)) {
    if (name !== 'window') window[name] = globals[name];
  }
  Object.defineProperty(window, 'localStorage', { get: () => globals.localStorage });
  vm.runInNewContext(source, globals, { filename: 'theme.js', timeout: 1000 });
  return {
    root, button, icon, meta, values, reads, writes, changes, network,
    ready() { ready = true; document.dispatchEvent({ type: 'DOMContentLoaded' }); },
    click() { button.dispatchEvent({ type: 'click' }); },
    storage(key, newValue) {
      if (key === null) values.clear();
      else if (newValue === null) values.delete(key);
      else values.set(key, newValue);
      window.dispatchEvent({ type: 'storage', key, newValue, storageArea: storage });
    },
    pageshow(persisted) { window.dispatchEvent({ type: 'pageshow', persisted }); },
  };
}

function assertState(harness, theme) {
  const dark = theme === 'dark';
  assert.equal(harness.root.dataset.bsTheme, theme);
  assert.equal(harness.button.hidden, false);
  assert.equal(harness.button.getAttribute('aria-pressed'), String(dark));
  assert.equal(harness.button.getAttribute('aria-label'), 'Dark theme');
  assert.equal(harness.button.title, dark ? 'Switch to light' : 'Switch to dark');
  assert.equal(harness.icon.className, dark ? 'bi bi-sun' : 'bi bi-moon');
  assert.equal(harness.meta.content, dark ? '#16181c' : LIGHT_COLOR);
  assert.deepEqual(harness.network, []);
}

for (const saved of ['dark', 'light', null, '', 'DARK', ' dark ', 'system', 'false', '__proto__', '<script>alert(1)</script>']) {
  test(`early boot validates saved preference ${JSON.stringify(saved)}`, () => {
    const harness = boot({ saved });
    const expected = saved === 'dark' ? 'dark' : 'light';
    assert.equal(harness.root.dataset.bsTheme, expected);
    assert.equal(harness.button.hidden, true);
    assert.equal(harness.meta.content, expected === 'dark' ? '#16181c' : LIGHT_COLOR);
    assert.deepEqual(harness.reads, [KEY]);
    assert.deepEqual(harness.writes, []);
    harness.ready();
    assertState(harness, expected);
    assert.deepEqual(harness.changes, []);
  });
}

test('missing preference defaults to light even on a dark-system device', () => {
  const harness = boot();
  harness.ready();
  assertState(harness, 'light');
  assert.deepEqual(harness.writes, []);
});

test('clicks update state, accessibility, icon, brand meta, scoped storage and events', () => {
  const harness = boot();
  harness.ready();
  for (const theme of ['dark', 'light', 'dark', 'light']) {
    harness.click();
    assertState(harness, theme);
    assert.equal(harness.values.get(KEY), theme);
  }
  assert.deepEqual(harness.writes, [[KEY, 'dark'], [KEY, 'light'], [KEY, 'dark'], [KEY, 'light']]);
  assert.deepEqual(harness.changes, ['dark', 'light', 'dark', 'light']);
});

test('saved dark restores the original tenant color when toggled to light', () => {
  const harness = boot({ saved: 'dark' });
  harness.ready();
  assertState(harness, 'dark');
  harness.click();
  assertState(harness, 'light');
  assert.deepEqual(harness.writes, [[KEY, 'light']]);
});

for (const failure of ['storageThrows', 'readThrows', 'writeThrows']) {
  test(`${failure} does not break initialization or subsequent clicks`, () => {
    const harness = boot({ [failure]: true });
    harness.ready();
    assertState(harness, 'light');
    harness.click();
    assertState(harness, 'dark');
    harness.click();
    assertState(harness, 'light');
    assert.deepEqual(harness.changes, ['dark', 'light']);
    if (failure === 'writeThrows') assert.equal(harness.values.has(KEY), false);
  });
}

for (const key of ['', undefined]) {
  test(`missing scope ${JSON.stringify(key)} never reads or writes a shared preference`, () => {
    const harness = boot({ key, entries: [['vp-theme', 'dark']] });
    harness.ready();
    assertState(harness, 'light');
    harness.click();
    assertState(harness, 'dark');
    assert.deepEqual(harness.reads, []);
    assert.deepEqual(harness.writes, []);
  });
}

test('other users, companies, guests and legacy preferences are not read or overwritten', () => {
  const entries = [['vp-theme:11:23', 'dark'], ['vp-theme:12:22', 'dark'], ['vp-theme:11:guest', 'dark'], ['vp-theme', 'dark']];
  const harness = boot({ entries });
  harness.ready();
  assertState(harness, 'light');
  harness.click();
  assertState(harness, 'dark');
  assert.deepEqual(harness.reads, [KEY]);
  assert.deepEqual(harness.writes, [[KEY, 'dark']]);
  for (const [key, value] of entries) assert.equal(harness.values.get(key), value);
});

test('matching cross-tab updates, removal, invalid values and clear synchronize without write loops', () => {
  const harness = boot();
  harness.ready();
  for (const [key, value, expected] of [
    [KEY, 'dark', 'dark'], [KEY, 'light', 'light'], [KEY, 'dark', 'dark'],
    [KEY, 'invalid', 'light'], [KEY, 'dark', 'dark'], [KEY, null, 'light'],
    [KEY, 'dark', 'dark'], [null, null, 'light'],
  ]) {
    harness.storage(key, value);
    assertState(harness, expected);
  }
  assert.deepEqual(harness.writes, []);
  assert.deepEqual(harness.changes, []);
});

test('foreign storage events do not change state or even read local storage', () => {
  const harness = boot();
  harness.ready();
  harness.values.set(KEY, 'dark');
  for (const key of ['vp-theme:11:23', 'vp-theme:12:22', 'vp-theme:public:guest', 'unrelated']) {
    harness.storage(key, 'dark');
    assertState(harness, 'light');
  }
  assert.deepEqual(harness.reads, [KEY]);
  assert.deepEqual(harness.writes, []);
});

test('storage event before DOMContentLoaded is retained when the toggle appears', () => {
  const harness = boot();
  harness.storage(KEY, 'dark');
  assert.equal(harness.root.dataset.bsTheme, 'dark');
  assert.equal(harness.button.hidden, true);
  harness.ready();
  assertState(harness, 'dark');
});

test('storage errors during cross-tab synchronization fall back to light', () => {
  const harness = boot({ readThrows: true });
  harness.ready();
  harness.click();
  assertState(harness, 'dark');
  harness.storage(KEY, 'dark');
  assertState(harness, 'light');
  assert.deepEqual(harness.writes, [[KEY, 'dark']]);
});

test('bfcache restoration re-reads the scoped preference without persisting', () => {
  const harness = boot();
  harness.ready();
  harness.values.set(KEY, 'dark');
  harness.pageshow(false);
  assertState(harness, 'light');
  assert.deepEqual(harness.reads, [KEY]);
  harness.pageshow(true);
  assertState(harness, 'dark');
  harness.values.delete(KEY);
  harness.pageshow(true);
  assertState(harness, 'light');
  assert.deepEqual(harness.writes, []);
});

for (const missing of ['noButton', 'noIcon', 'noMeta']) {
  test(`${missing} does not prevent early boot or storage synchronization`, () => {
    const harness = boot({ [missing]: true, saved: 'dark' });
    harness.ready();
    assert.equal(harness.root.dataset.bsTheme, 'dark');
    harness.storage(KEY, 'light');
    assert.equal(harness.root.dataset.bsTheme, 'light');
    assert.deepEqual(harness.network, []);
  });
}
