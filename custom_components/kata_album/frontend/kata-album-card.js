/* Kata Album card: photo and people gallery. No external deps, no persistent image storage. */
const MAX_THUMBS = 4;
const LIST_TTL_MS = 10 * 60 * 1000;

class Limiter {
  constructor(max) { this.max = max; this.active = 0; this.queue = []; }
  run(task, signal) {
    return new Promise((resolve, reject) => {
      const start = () => {
        if (signal.aborted) { this._next(); return reject(new DOMException("aborted", "AbortError")); }
        this.active++;
        task().then(resolve, reject).finally(() => { this.active--; this._next(); });
      };
      this.active < this.max ? start() : this.queue.push(start);
    });
  }
  _next() { while (this.active < this.max && this.queue.length) this.queue.shift()(); }
}

function addDays(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}
function daysBetween(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }

const STYLE = `
:host{display:block}
ha-card{overflow:hidden}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;
  padding:16px 16px 12px}
.ttl h2{margin:0;font-size:1.25rem;font-weight:600;letter-spacing:-.01em}
.ttl p{margin:2px 0 0;font-size:.85rem;color:var(--secondary-text-color)}
.ctl{display:flex;gap:8px;align-items:center}
.ctl input[type=date]{font:inherit;color:var(--primary-text-color);background:var(--secondary-background-color);
  border:1px solid var(--divider-color);border-radius:999px;padding:6px 12px}
.pill{font:inherit;cursor:pointer;color:var(--primary-text-color);background:var(--secondary-background-color);
  border:1px solid var(--divider-color);border-radius:999px;padding:6px 14px}
.pill:hover{background:var(--divider-color)}
.body{padding:0 16px 16px;max-height:var(--kata-body-height,70vh);overflow:auto}
[hidden]{display:none!important}
.pill[aria-pressed=true]{background:var(--primary-color);color:var(--text-primary-color,#fff)}
.people-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:12px}
.person{display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px;border-radius:12px;
  border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer}
.person img,.avatar{width:64px;height:64px;border-radius:50%;object-fit:cover;background:var(--divider-color)}
.person span{max-width:100%;overflow-wrap:anywhere}

.day{margin-top:20px}
.day:first-child{margin-top:4px}
.dh{display:flex;align-items:baseline;gap:8px;margin:0 0 8px}
.dh h3{margin:0;font-size:1.05rem;font-weight:600}
.dh span{font-size:.8rem;color:var(--secondary-text-color)}
.grid{display:grid;gap:6px}
.tile{position:relative;aspect-ratio:16/9;border:0;padding:0;cursor:pointer;overflow:hidden;
  border-radius:10px;background:var(--secondary-background-color)}
.tile.load::after{content:"";position:absolute;inset:0;
  background:linear-gradient(100deg,transparent 30%,rgba(127,127,127,.18) 50%,transparent 70%);
  background-size:200% 100%;animation:sh 1.3s infinite}
@keyframes sh{from{background-position:200% 0}to{background-position:-200% 0}}
.tile img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .25s ease}
.tile:hover img,.tile:focus-visible img{transform:scale(1.05)}
.tile:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
.tile .t{position:absolute;left:6px;bottom:6px;font-size:.72rem;color:#fff;padding:2px 7px;
  border-radius:999px;background:rgba(0,0,0,.55);opacity:0;transition:opacity .15s}
.tile:hover .t,.tile:focus-visible .t{opacity:1}
@media (hover:none){.tile .t{opacity:1}}
.tile.bad{display:grid;place-items:center;color:var(--secondary-text-color)}
.msg{padding:28px 16px;text-align:center;color:var(--secondary-text-color)}
.msg.err{color:var(--error-color)}
dialog{border:0;padding:0;margin:0;width:100vw;height:100vh;max-width:none;max-height:none;
  background:rgba(8,8,10,.96);color:#fff}
dialog::backdrop{background:#000}
.lb{position:relative;width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  touch-action:pan-y}
.lb img{max-width:100%;max-height:100%;object-fit:contain;display:block;user-select:none}
.lb img.ph{filter:blur(6px);transform:scale(1.02)}
.top{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:12px;
  padding:max(12px,env(safe-area-inset-top)) 16px 28px;
  background:linear-gradient(rgba(0,0,0,.65),transparent);z-index:2}
.top .cap{flex:1;min-width:0}
.top .cap b{display:block;font-weight:600}
.top .cap small{opacity:.75}
.lb .pill{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.25);color:#fff}
.lb .pill:hover{background:rgba(255,255,255,.26)}
.nav{position:absolute;top:50%;transform:translateY(-50%);z-index:2;width:48px;height:48px;border-radius:50%;
  border:0;cursor:pointer;font-size:1.6rem;line-height:1;color:#fff;background:rgba(255,255,255,.14)}
.nav:hover{background:rgba(255,255,255,.28)}
.nav[disabled]{opacity:.25;cursor:default}
.prev{left:12px}.next{right:12px}
.spin{position:absolute;z-index:1;width:36px;height:36px;border-radius:50%;
  border:3px solid rgba(255,255,255,.25);border-top-color:#fff;animation:rot .8s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}
@media (max-width:600px){.nav{display:none}}
`;

class KataAlbumCard extends HTMLElement {
  setConfig(config) {
    if (!config.entry_id) throw new Error("entry_id is required");
    this._config = { page_size: 60, days_per_load: 7, max_days: 365, min_tile: 160,
      title: "Kata Album", ...config };
    this._config.days_per_load = Math.min(31, Math.max(1, this._config.days_per_load));
    this._listCache = new Map();
    this._blobs = new Set();
    this._thumbs = new Limiter(MAX_THUMBS);
    this._full = new Limiter(1);
    this._gen = 0;
    this._built = false;
    this._mode = "album"; this._person = null; this._collapsed = false;
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._date = this._today(); this._build(); this._built = true; this._load(); }
  }
  getCardSize() { return 6; }
  disconnectedCallback() { this._cancel(); }
  connectedCallback() { if (this._built && !this._ctl) this._load(); }

  /* ---------- helpers ---------- */
  get _tz() { return this._hass?.config?.time_zone; }
  _today() { return new Intl.DateTimeFormat("en-CA", { timeZone: this._tz }).format(new Date()); }
  _label(iso) {
    const today = this._today();
    if (iso === today) return "Today";
    if (iso === addDays(today, -1)) return "Yesterday";
    return new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined,
      { weekday: "long", timeZone: "UTC" });
  }
  _dateText(iso) {
    return new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined,
      { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }
  _time(item) {
    return item.captured_at ? new Date(item.captured_at).toLocaleTimeString(undefined,
      { hour: "2-digit", minute: "2-digit", timeZone: this._tz }) : "";
  }
  $(id) { return this.shadowRoot.getElementById(id); }

  /* ---------- structure ---------- */
  _build() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card>
        <div class="bar">
          <div class="ttl"><h2></h2><p id="sub"></p></div>
          <div class="ctl">
            <button class="pill" id="album" aria-pressed="true">Album</button>
            <button class="pill" id="people" aria-pressed="false">People</button>
            <button class="pill" id="collapse" aria-expanded="true">Collapse</button>
          </div>
          <div class="ctl" id="dates"><input type="date" id="date" aria-label="Jump to date">
            <button class="pill" id="today">Today</button></div>
        </div>
        <div class="body" id="body"><button class="pill" id="back" hidden>← People</button><div id="list"></div><div class="msg" id="msg"></div><div id="sentinel"></div></div>
        <dialog id="dlg"><div class="lb" id="lb">
          <div class="top"><div class="cap"><b id="c1"></b><small id="c2"></small></div>
            <button class="pill" id="orig">Original</button><button class="pill" id="delete">Delete</button>
            <button class="pill" id="close" aria-label="Close">✕</button></div>
          <button class="nav prev" id="prev" aria-label="Previous">‹</button>
          <button class="nav next" id="next" aria-label="Next">›</button>
          <div class="spin" id="spin" hidden></div><img id="big" alt="">
        </div></dialog>
      </ha-card>`;
    this.shadowRoot.querySelector("h2").textContent = this._config.title;
    this.style.setProperty("--kata-body-height", `${Math.max(200, Number(this._config.max_height) || 640)}px`);
    this.$("album").addEventListener("click", () => this._switchMode("album"));
    this.$("people").addEventListener("click", () => this._switchMode("people"));
    this.$("back").addEventListener("click", () => { this._person = null; this._loadPeople(); });
    this.$("collapse").addEventListener("click", () => {
      this._collapsed = !this._collapsed;
      this.$("body").hidden = this._collapsed;
      this.$("collapse").textContent = this._collapsed ? "Expand" : "Collapse";
      this.$("collapse").setAttribute("aria-expanded", String(!this._collapsed));
      if (this._collapsed) this._cancel(); else this._load();
    });
    this.$("delete").addEventListener("click", () => this._deletePhoto());
    const input = this.$("date");
    input.value = this._date; input.max = this._today();
    input.addEventListener("change", () => { this._date = input.value || this._today(); this._load(); });
    this.$("today").addEventListener("click", () => { this._date = this._today(); input.value = this._date; this._load(); });
    this._sentinel = this.$("sentinel");
    this._sentinel._load = () => this._more();
    this._io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { this._io.unobserve(e.target); e.target._load?.(); }
    }, { root: this.$("body"), rootMargin: "400px" });

    const dlg = this.$("dlg");
    dlg.addEventListener("close", () => this._closeViewer());
    this.$("close").addEventListener("click", () => dlg.close());
    this.$("prev").addEventListener("click", () => this._step(-1));
    this.$("next").addEventListener("click", () => this._step(1));
    this.$("orig").addEventListener("click", () => this._show(this._idx, true));
    this.$("lb").addEventListener("click", (e) => { if (e.target === this.$("lb")) dlg.close(); });
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") this._step(-1);
      else if (e.key === "ArrowRight") this._step(1);
    });
    let x0 = null;
    const lb = this.$("lb");
    lb.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    lb.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0; x0 = null;
      if (Math.abs(dx) > 50) this._step(dx < 0 ? 1 : -1);
    });
  }

  _cancel() {
    this._gen++;
    this._ctl?.abort(); this._ctl = null;
    this._viewCtl?.abort();
    this._io?.disconnect();
    for (const u of this._blobs) URL.revokeObjectURL(u);
    this._blobs.clear();
  }
  async _fetch(url, signal, options = {}) {
    const path = url.startsWith("/") ? url : `/${url}`;
    const res = this._hass.fetchWithAuth
      ? await this._hass.fetchWithAuth(path, { ...options, signal, cache: "no-store" })
      : await fetch(this._hass.hassUrl(path), {
          ...options, headers: { ...options.headers, Authorization: `Bearer ${this._hass.auth.data.access_token}` },
          cache: "no-store", signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  }
  _setMsg(text, { err = false, retry = false } = {}) {
    const m = this.$("msg");
    m.className = "msg" + (err ? " err" : "");
    m.textContent = text;
    if (retry) {
      const b = document.createElement("button");
      b.className = "pill"; b.textContent = "Retry";
      b.addEventListener("click", () => { this._busy = false; this._more(); });
      m.append(document.createElement("br"), b);
    }
    m.hidden = !text;
  }
  _summary() {
    const days = new Set(this._items.map((i) => i.date)).size;
    this.$("sub").textContent = this._person
      ? `${this._person.name || "Person"} · ${this._items.length} loaded${this._personTotal === null ? "" : ` / ${this._personTotal} total`}`
      : this._items.length
      ? `${this._items.length} photos · ${days} day${days === 1 ? "" : "s"}${this._done ? "" : " loaded"}`
      : "";
  }

  /* ---------- loading ---------- */
  _load() {
    if (this._collapsed) return;
    if (this._mode === "people" && !this._person) { this._loadPeople(); return; }
    this.$("back").hidden = !this._person;
    this._cursor = null;
    this._cancel();
    this._gen++;
    this._ctl = new AbortController();
    this._personTotal = null;
    if (this._person?.group === "familiar") this._loadPersonStats(this._person, this._gen, this._ctl.signal);
    this.$("list").replaceChildren();
    this._items = []; this._rendered = 0; this._lastDate = null; this._grid = null;
    this._oldest = addDays(this._date, 1);
    this._done = false; this._busy = false;
    this._summary();
    this._more();
  }

  async _more() {
    if (this._busy) return;
    this._busy = true;
    const gen = this._gen, signal = this._ctl.signal;
    try {
      while (this._rendered >= this._items.length && !this._done) {
        this._setMsg("Loading…");
        await this._loadWindow(gen, signal);
        if (gen !== this._gen) return;
      }
      if (gen !== this._gen) return;
      this._renderPage();
      this._summary();
      if (!this._items.length) this._setMsg(this._person ? "No photos for this person." : `No photos in the last ${this._config.max_days} days.`);
      else if (this._done && this._rendered >= this._items.length) this._setMsg("You've reached the end.");
      else this._setMsg("");
    } catch (e) {
      if (e.name === "AbortError" || gen !== this._gen) return;
      this._setMsg("Album unavailable. Check the Kata Album status entity.", { err: true, retry: true });
      return; // no automatic retry
    } finally { if (gen === this._gen) this._busy = false; }
    if (this._rendered < this._items.length || !this._done) {
      this._io.unobserve(this._sentinel); this._io.observe(this._sentinel);
    }
  }

  async _loadWindow(gen, signal) {
    if (this._person) {
      let url = `/api/kata_album/${this._config.entry_id}/people/${this._person.id}/photos`;
      if (this._cursor !== null) url += `?cursor=${this._cursor}`;
      const data = await (await this._fetch(url, signal)).json();
      if (gen !== this._gen) return;
      const ids = new Set(this._items.map(i => i.id));
      const fresh = data.items.filter(i => !ids.has(i.id));
      this._items.push(...fresh);
      this._done = data.done || !fresh.length || data.next_cursor === this._cursor;
      this._cursor = data.next_cursor;
      return;
    }
    const last = addDays(this._oldest, -1);
    const first = addDays(last, -(this._config.days_per_load - 1));
    const today = this._today();
    if (daysBetween(first, today) > this._config.max_days + this._config.days_per_load) { this._done = true; return; }
    const key = `${this._config.entry_id}|${first}|${last}`;
    let hit = this._listCache.get(key);
    if (!hit || Date.now() - hit.t > LIST_TTL_MS) {
      const res = await this._fetch(`/api/kata_album/${this._config.entry_id}/photos?start=${first}&end=${last}`, signal);
      hit = { t: Date.now(), data: await res.json() };
      this._listCache.set(key, hit);
    }
    if (gen !== this._gen) return;
    this._items.push(...hit.data.items);
    this._oldest = first;
    if (daysBetween(first, today) >= this._config.max_days) this._done = true;
  }

  /* ---------- gallery ---------- */
  _renderPage() {
    const list = this.$("list");
    const gen = this._gen, signal = this._ctl.signal;
    const start = this._rendered;
    const next = this._items.slice(start, start + this._config.page_size);
    this._rendered += next.length;
    next.forEach((item, k) => {
      const idx = start + k;
      if (!this._grid || item.date !== this._lastDate) {
        const sec = document.createElement("section"); sec.className = "day";
        const h = document.createElement("div"); h.className = "dh";
        const t = document.createElement("h3"); t.textContent = item.date ? this._label(item.date) : "Unknown date";
        const s = document.createElement("span");
        const n = this._items.filter((i) => i.date === item.date).length;
        s.textContent = `${item.date ? this._dateText(item.date) + " · " : ""}${n} photo${n === 1 ? "" : "s"}`;
        h.append(t, s);
        this._grid = document.createElement("div"); this._grid.className = "grid";
        this._grid.style.gridTemplateColumns = this._config.columns
          ? `repeat(${this._config.columns},1fr)`
          : `repeat(auto-fill,minmax(${this._config.min_tile}px,1fr))`;
        sec.append(h, this._grid); list.append(sec);
        this._lastDate = item.date;
      }
      const tile = document.createElement("button");
      tile.className = "tile load";
      tile.setAttribute("aria-label", `Open photo ${this._time(item)}`);
      const stamp = document.createElement("span"); stamp.className = "t"; stamp.textContent = this._time(item);
      tile.append(stamp);
      tile._load = async () => {
        try {
          const blob = await this._thumbs.run(async () => (await this._fetch(item.thumbnail_url, signal)).blob(), signal);
          if (gen !== this._gen) return;
          const url = URL.createObjectURL(blob); this._blobs.add(url);
          item._thumb = url;
          const img = new Image(); img.src = url; img.alt = ""; img.decoding = "async";
          tile.classList.remove("load"); tile.prepend(img);
        } catch (e) {
          if (e.name !== "AbortError") { tile.classList.remove("load"); tile.classList.add("bad"); tile.textContent = "!"; }
        } // no retry loop
      };
      tile.addEventListener("click", () => this._open(idx));
      this._grid.appendChild(tile);
      this._io.observe(tile);
    });
  }

  _switchMode(mode) {
    this._mode = mode; this._person = null;
    this.$("album").setAttribute("aria-pressed", String(mode === "album"));
    this.$("people").setAttribute("aria-pressed", String(mode === "people"));
    this.$("dates").hidden = mode === "people";
    this.$("back").hidden = true;
    this._load();
  }

  async _loadPeople() {
    if (this._collapsed) return;
    this._cancel(); const gen = ++this._gen;
    this._ctl = new AbortController(); const signal = this._ctl.signal;
    this.$("list").replaceChildren(); this.$("back").hidden = true;
    this.$("sub").textContent = ""; this._setMsg("Loading people…");
    try {
      const data = await (await this._fetch(`/api/kata_album/${this._config.entry_id}/people`, signal)).json();
      if (gen !== this._gen) return;
      this.$("sub").textContent = `${data.items.length} people`;
      for (const group of ["familiar", "stranger"]) {
        const people = data.items.filter(p => p.group === group);
        if (!people.length) continue;
        const heading = document.createElement("h3"); heading.textContent = group === "familiar" ? "Familiar" : "Strangers";
        const grid = document.createElement("div"); grid.className = "people-grid";
        this.$("list").append(heading, grid);
        people.forEach((person, idx) => {
          const button = document.createElement("button"); button.className = "person";
          const avatar = document.createElement("span"); avatar.className = "avatar";
          const label = document.createElement("span"); label.textContent = person.name || `${group === "familiar" ? "Person" : "Stranger"} ${idx + 1}`;
          button.append(avatar, label); grid.append(button);
          button.addEventListener("click", () => { this._person = person; this._load(); });
          if (person.avatar_url) {
            button._load = async () => {
              try {
                const blob = await this._thumbs.run(async () => (await this._fetch(person.avatar_url, signal)).blob(), signal);
                if (gen !== this._gen) return;
                const url = URL.createObjectURL(blob); this._blobs.add(url);
                const image = new Image(); image.alt = ""; image.src = url; avatar.replaceWith(image);
              } catch (_) { /* Keep placeholder; no background retries. */ }
            };
            this._io.observe(button);
          }
        });
      }
      this._setMsg(data.items.length ? "" : "No people found.");
    } catch (e) {
      if (gen !== this._gen || e.name === "AbortError") return;
      this._setMsg("People unavailable.", { err: true });
      const retry = document.createElement("button"); retry.className = "pill"; retry.textContent = "Retry";
      retry.onclick = () => this._loadPeople(); this.$("msg").append(retry);
    }
  }

  async _loadPersonStats(person, gen, signal) {
    try {
      const data = await (await this._fetch(`/api/kata_album/${this._config.entry_id}/people/${person.id}/stats`, signal)).json();
      if (gen !== this._gen || signal.aborted) return;
      this._personTotal = Number.isFinite(data.total) ? data.total : null; this._summary();
    } catch (_) { /* Stats failure must not prevent photo browsing. */ }
  }

  async _deletePhoto() {
    const item = this._items[this._idx];
    if (!item || this._deleting) return;
    if (!window.confirm(`Permanently delete this photo from Kata Friend?\n${item.captured_at || ""}\nThis cannot be undone.`)) return;
    this._deleting = true; this.$("delete").disabled = true;
    try {
      await this._fetch(`/api/kata_album/${this._config.entry_id}/photos`, this._ctl.signal,
        { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: item.id, confirm: true }) });
      this._listCache.clear(); this.$("dlg").close(); this._load();
    } catch (e) {
      this._listCache.clear();
      this.$("dlg").close(); this._load();
      window.alert("Deletion could not be confirmed. The list is being reloaded; check before retrying.");
    } finally { this._deleting = false; this.$("delete").disabled = false; }
  }

  /* ---------- viewer ---------- */
  _open(idx) {
    this.$("dlg").showModal();
    this._show(idx, false);
  }
  async _step(d) {
    const i = this._idx + d;
    if (i >= this._items.length && !this._done) await this._more();
    if (i < 0 || i >= this._items.length) return;
    this._show(i, false);
  }
  async _show(idx, original) {
    const item = this._items[idx];
    if (!item) return;
    this._idx = idx;
    this._viewCtl?.abort();
    const ctl = this._viewCtl = new AbortController();
    this.$("c1").textContent = item.date ? `${this._label(item.date)}, ${this._dateText(item.date)}` : "Photo";
    this.$("c2").textContent = `${this._time(item)} · ${idx + 1} / ${this._items.length}${this._done ? "" : "+"}`;
    this.$("prev").disabled = idx === 0;
    this.$("next").disabled = idx >= this._items.length - 1 && this._done;
    this.$("orig").hidden = original;
    const big = this.$("big");
    if (item._thumb && !original) { big.src = item._thumb; big.className = "ph"; }
    this.$("spin").hidden = false;
    try {
      const url = original ? item.original_url : item.preview_url;
      const blob = await this._full.run(async () => (await this._fetch(url, ctl.signal)).blob(), ctl.signal);
      if (ctl.signal.aborted) return;
      if (this._viewUrl) URL.revokeObjectURL(this._viewUrl);
      this._viewUrl = URL.createObjectURL(blob);
      big.src = this._viewUrl; big.className = "";
    } catch (e) {
      if (e.name !== "AbortError") this.$("c2").textContent += " · could not load";
    } finally { if (!ctl.signal.aborted) this.$("spin").hidden = true; }
  }
  _closeViewer() {
    this._viewCtl?.abort();
    if (this._viewUrl) URL.revokeObjectURL(this._viewUrl);
    this._viewUrl = null;
    this.$("big").removeAttribute("src");
  }
}
if (!customElements.get("kata-album-card")) customElements.define("kata-album-card", KataAlbumCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "kata-album-card", name: "Kata Album", description: "Kata Friend photos and people" });
