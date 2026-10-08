/* Card logic tests with browser doubles; no HA/browser rendering is implied. */
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../custom_components/kata_album/frontend/kata-album-card.js'), 'utf8');
let Card;
vm.runInNewContext(source, {
  HTMLElement: class {},
  customElements: { get: () => false, define: (_, cls) => { Card = cls; } },
  window: { customCards: [], confirm: () => true, alert: () => {} },
  AbortController, URL, Date, Intl, Set, Map, Number, DOMException,
});
function card() {
  const c = new Card();
  c.setConfig({entry_id: 'entry'});
  c._ctl = new AbortController();
  c._items = [];
  c._person = {id: 'person', name: 'Person', group: 'familiar'};
  c._cursor = null;
  return c;
}

test('person review starts with server current time and advances cursor', async () => {
  const c = card(); let url;
  c._fetch = async u => { url = u; return {json: async () => ({items: [{id: 'p1'}], next_cursor: 100, done: false})}; };
  await c._loadWindow(c._gen, c._ctl.signal);
  assert.equal(url, '/api/kata_album/entry/people/person/photos');
  assert.equal(c._cursor, 100);
  await c._loadWindow(c._gen, c._ctl.signal);
  assert.match(url, /cursor=100$/);
  assert.equal(c._items.length, 1);
  assert.equal(c._done, true); // Repeated results must terminate.
});

test('switching views invalidates stale in-flight responses', async () => {
  const c = card(); let finish;
  c._fetch = () => new Promise(resolve => { finish = resolve; });
  const pending = c._loadWindow(c._gen, c._ctl.signal);
  c._cancel();
  finish({json: async () => ({items: [{id: 'stale'}], next_cursor: 100, done: false})});
  await pending;
  assert.equal(c._items.length, 0);
});

test('people mode hides date controls and starts a separate view', () => {
  const c = card(); const els = {};
  c.$ = id => els[id] ||= {setAttribute() {}, hidden: false};
  c._load = () => { c.loaded = true; };
  c._switchMode('people');
  assert.equal(c._person, null);
  assert.equal(els.dates.hidden, true);
  assert.equal(c.loaded, true);
});

test('delete sends opaque ID and explicit confirmation, clears browser cache', async () => {
  const c = card(); c._items = [{id: 'opaque'}]; c._idx = 0;
  c._listCache.set('old', {});
  const els = {delete: {disabled: false}, dlg: {close() {}}};
  c.$ = id => els[id]; c._load = () => {};
  let options;
  c._fetch = async (_, __, o) => { options = o; return {}; };
  await c._deletePhoto();
  assert.equal(options.method, 'DELETE');
  assert.deepEqual(JSON.parse(options.body), {id: 'opaque', confirm: true});
  assert.equal(c._listCache.size, 0);
  assert.equal(els.delete.disabled, false);
});

test('missing person statistics do not block photo browsing', async () => {
  const c = card(); c._personTotal = null;
  c._fetch = async () => { throw new Error('unavailable'); };
  await c._loadPersonStats(c._person, c._gen, c._ctl.signal);
  assert.equal(c._personTotal, null);
});
