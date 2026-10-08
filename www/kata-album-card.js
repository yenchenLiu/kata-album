/* Kata Album card: read-only, no external deps, no persistent image storage. */
const MAX_THUMBS = 4;
const LIST_TTL_MS = 10 * 60 * 1000;

class Limiter {
  constructor(max) { this.max = max; this.active = 0; this.queue = []; }
  run(task, signal) {
    return new Promise((resolve, reject) => {
      const start = () => {
        if (signal.aborted) return reject(new DOMException("aborted", "AbortError"));
        this.active++;
        task().then(resolve, reject).finally(() => { this.active--; this._next(); });
      };
      this.active < this.max ? start() : this.queue.push(start);
    });
  }
  _next() { while (this.active < this.max && this.queue.length) this.queue.shift()(); }
}

class KataAlbumCard extends HTMLElement {
  setConfig(config) {
    if (!config.entry_id) throw new Error("entry_id is required");
    this._config = { columns: 3, page_size: 50, title: "Kata Album", ...config };
    this._listCache = new Map();
    this._blobs = new Set();
    this._thumbs = new Limiter(MAX_THUMBS);
    this._originals = new Limiter(1);
    this._gen = 0;
    this._date = this._today();
    this._built = false;
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._build(); this._built = true; this._load(); }
  }
  getCardSize() { return 6; }
  disconnectedCallback() { this._cancel(); }
  connectedCallback() { if (this._built && !this._ctl) this._load(); }

  _today() {
    const tz = this._hass?.config?.time_zone;
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date());
  }
  _build() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        ha-card{padding:12px}
        header{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}
        h2{margin:0;font-size:1.1em}
        .grid{display:grid;gap:4px;margin-top:8px}
        .cell{aspect-ratio:1;background:var(--secondary-background-color);overflow:hidden;cursor:pointer;border:0;padding:0}
        .cell img{width:100%;height:100%;object-fit:cover;display:block}
        .msg{padding:16px;text-align:center;color:var(--secondary-text-color)}
        .err{color:var(--error-color)}
        dialog{border:0;padding:0;max-width:96vw;max-height:96vh;background:#000}
        dialog img{max-width:96vw;max-height:90vh;display:block}
        button.more{margin:8px auto;display:block}
      </style>
      <ha-card>
        <header><h2></h2><input type="date"></header>
        <div class="msg" id="msg"></div>
        <div class="grid" id="grid"></div>
        <button class="more" id="more" hidden>Load more</button>
        <dialog id="dlg"><img id="big" alt=""></dialog>
      </ha-card>`;
    const r = this.shadowRoot;
    r.querySelector("h2").textContent = this._config.title;
    this._input = r.querySelector("input");
    this._input.value = this._date;
    this._input.addEventListener("change", () => { this._date = this._input.value || this._today(); this._load(); });
    r.getElementById("more").addEventListener("click", () => this._renderPage());
    r.getElementById("dlg").addEventListener("close", () => this._closeOriginal());
    r.getElementById("dlg").addEventListener("click", () => r.getElementById("dlg").close());
    r.getElementById("grid").style.gridTemplateColumns = `repeat(${this._config.columns},1fr)`;
    this._io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { this._io.unobserve(e.target); e.target._load?.(); }
    }, { rootMargin: "200px" });
  }

  _cancel() {
    this._ctl?.abort(); this._ctl = null;
    this._io?.disconnect();
    for (const u of this._blobs) URL.revokeObjectURL(u);
    this._blobs.clear();
  }
  async _fetch(url, signal) {
    const path = url.startsWith("/") ? url : `/${url}`;
    const res = this._hass.fetchWithAuth
      ? await this._hass.fetchWithAuth(path, { signal, cache: "no-store" })
      : await fetch(this._hass.hassUrl(path), {
          headers: { Authorization: `Bearer ${this._hass.auth.data.access_token}` },
          cache: "no-store", signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  }
  _setMsg(text, err = false) {
    const m = this.shadowRoot.getElementById("msg");
    m.textContent = text; m.className = "msg" + (err ? " err" : "");
  }

  async _load() {
    this._cancel();
    const gen = ++this._gen;
    const ctl = this._ctl = new AbortController();
    this.shadowRoot.getElementById("grid").replaceChildren();
    this.shadowRoot.getElementById("more").hidden = true;
    this._items = []; this._shown = 0;
    this._setMsg("Loading…");
    const key = `${this._config.entry_id}|${this._date}`;
    try {
      let hit = this._listCache.get(key);
      if (!hit || Date.now() - hit.t > LIST_TTL_MS) {
        const res = await this._fetch(`/api/kata_album/${this._config.entry_id}/photos?date=${this._date}`, ctl.signal);
        hit = { t: Date.now(), data: await res.json() };
        this._listCache.set(key, hit);
      }
      if (gen !== this._gen) return; // stale response from a previous date
      this._items = hit.data.items;
      this._setMsg(this._items.length ? "" : "No photos on this day.");
      this._renderPage();
    } catch (e) {
      if (e.name === "AbortError" || gen !== this._gen) return;
      this._setMsg("Album unavailable. Check the Kata Album status entity.", true);
    }
  }

  _renderPage() {
    const grid = this.shadowRoot.getElementById("grid");
    const gen = this._gen, signal = this._ctl.signal;
    const next = this._items.slice(this._shown, this._shown + this._config.page_size);
    this._shown += next.length;
    for (const item of next) {
      const cell = document.createElement("button");
      cell.className = "cell";
      cell.title = item.captured_at || "";
      cell._load = async () => {
        try {
          const blob = await this._thumbs.run(async () => (await this._fetch(item.thumbnail_url, signal)).blob(), signal);
          if (gen !== this._gen) return;
          const url = URL.createObjectURL(blob); this._blobs.add(url);
          const img = new Image(); img.src = url; img.alt = "";
          cell.replaceChildren(img);
        } catch (e) { if (e.name !== "AbortError") cell.textContent = "!"; } // no retry loop
      };
      cell.addEventListener("click", () => this._openOriginal(item));
      grid.appendChild(cell);
      this._io.observe(cell);
    }
    this.shadowRoot.getElementById("more").hidden = this._shown >= this._items.length;
  }

  async _openOriginal(item) {
    const dlg = this.shadowRoot.getElementById("dlg");
    this._origCtl?.abort();
    const ctl = this._origCtl = new AbortController();
    try {
      const blob = await this._originals.run(async () => (await this._fetch(item.original_url, ctl.signal)).blob(), ctl.signal);
      if (ctl.signal.aborted) return;
      this._origUrl = URL.createObjectURL(blob);
      this.shadowRoot.getElementById("big").src = this._origUrl;
      dlg.showModal();
    } catch (e) { if (e.name !== "AbortError") this._setMsg("Could not load original.", true); }
  }
  _closeOriginal() {
    this._origCtl?.abort();
    if (this._origUrl) URL.revokeObjectURL(this._origUrl);
    this._origUrl = null;
    this.shadowRoot.getElementById("big").removeAttribute("src");
  }
}
customElements.define("kata-album-card", KataAlbumCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "kata-album-card", name: "Kata Album", description: "Read-only Kata Friend photo browser" });
