// Korisnicka stranica za POST /query. Bez biblioteka i bez build koraka.
//
// Dva pogleda:
//   Pitaj              pitanje -> odgovor (varijanta B) -> izvori; A na zahtev.
//                      Kad sistem ne odgovara (ugasen GPU ili vektorska baza,
//                      isteklo vreme, mrezna greska), pitanje iz skupa za
//                      evaluaciju dobija SNIMLJEN odgovor, uvek oznacen kao snimljen.
//   Rezultati merenja  zbirna tabela i svih 106 pitanja iz snimka merenja.
//
// Sav tekst koji dolazi od modela ili iz dokumenata ide kroz textContent,
// nikad kroz innerHTML: odgovor generatora je nepoverljiv ulaz.
//
// Fajlovi koje stranica cita (postavlja ih RagQueryStack):
//   config.json               adresa API-ja i region (pri deploy-u)
//   snimljeno/snimljeno.json  snimak merenja (evaluation/export_ui.py), opcion
//   pitanja.json              skup pitanja, kad snimka nema
// API kljuc NIJE ni u jednom od njih: stranica je javna. Unosi se u polje i
// cuva samo u localStorage ovog pregledaca.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const store = {
    get(k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* privatni prozor */ } },
  };

  const OK = 0.75; // prag iz izvestaja: tacno = AnswerAccuracy >= 0.75
  const TYPE = { text: "tekst", table: "tabela", image: "slika" };
  const EXAMPLES = ["N3", "K3", "C2", "F1", "X2"];
  const EXAMPLE_LABEL = { tekst: "tekst", tabela: "tabela", dijagram: "dijagram", grafikon: "grafikon", "vise-dokumenata": "dva dokumenta" };
  const ERRORS = {
    400: "Neispravan zahtev",
    403: "API ključ nedostaje ili nije ispravan (Veza sa API-jem).",
    429: "Previše zahteva. Sačekaj trenutak pa pokušaj ponovo.",
    500: "Greška pri obradi pitanja.",
    503: "GPU sloj nije dostupan: GPU instanca ili vektorska baza nisu podignuti, ili se model još učitava.",
    504: "Isteklo vreme odgovora (API Gateway prekida posle 29 s).",
  };
  // Na snimak se prelazi samo kad SISTEM ne odgovara; greska u podesavanju
  // (pogresan kljuc, neispravan zahtev) se prikazuje da bi se ispravila.
  const systemDown = (status) => status === 0 || status >= 500;

  let CONFIG = {};
  let SNAP = null;            // snimak merenja ili null
  let SNAP_BY_ID = {};
  let QUESTIONS = [];         // {id, q, tip} — za primere i predloge
  let BY_TEXT = {};

  // ================= pomocne =================

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  const num = (x, d) => x.toFixed(d).replace(".", ",");
  const sec = (ms) => ms >= 1000 ? num(ms / 1000, 1) + " s" : Math.round(ms) + " ms";
  // p-vrednost zaokruzena kao u izvestaju (Python: polovina ka parnoj cifri), da se brojevi poklope sa radom.
  function pval(p) {
    const y = p * 1000, f = Math.floor(y);
    const r = Math.abs(y - f - 0.5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(y);
    return num(r / 1000, 3);
  }
  const norm = (s) => s.toLowerCase().replace(/[?.!\s]+/g, " ").trim();
  const words = (s) => norm(s).split(" ").filter((w) => w.length >= 3);
  function dateSr(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? Number(m[3]) + ". " + Number(m[2]) + ". " + m[1] + "." : "";
  }
  async function loadJson(path) {
    try {
      const r = await fetch(path, { cache: "no-store" });
      return r.ok ? await r.json() : null;
    } catch (e) {
      return null; // npr. otvoreno kao file://
    }
  }

  // ================= statistika snimka =================

  const isOk = (q, v) => q[v].acc !== null && q[v].acc !== undefined && q[v].acc >= OK;
  function relevantRank(q) {
    for (let i = 0; i < q.ctx.length; i++) {
      const c = SNAP.chunks[q.ctx[i][0]];
      if (q.docs.includes(c.doc) && (!q.slika || c.type === "image")) return i + 1;
    }
    return null;
  }
  function mcnemar(b, c) {
    const n = b + c;
    if (!n) return 1;
    let comb = 1, tail = 0;
    for (let i = 0; i <= Math.min(b, c); i++) {
      if (i > 0) comb = comb * (n - i + 1) / i;
      tail += comb;
    }
    return Math.min(1, 2 * tail / Math.pow(2, n));
  }
  const GROUPS = [
    ["sva", "Sva pitanja", () => true, false],
    ["slika", "Odgovor samo na slici", (q) => q.slika, false],
    ["tesko", "od toga teško za opis", (q) => q.tesko, true],
    ["tekst", "Tekst, tabela, više dokumenata", (q) => !q.slika, false],
  ];
  function summarize(qs) {
    const a = qs.filter((q) => isOk(q, "A")).length, b = qs.filter((q) => isOk(q, "B")).length;
    const onlyA = qs.filter((q) => isOk(q, "A") && !isOk(q, "B")).length;
    const onlyB = qs.filter((q) => !isOk(q, "A") && isOk(q, "B")).length;
    const ranks = qs.map(relevantRank);
    return { n: qs.length, a, b, onlyA, onlyB, p: mcnemar(onlyA, onlyB),
             hit: ranks.filter((r) => r !== null).length / qs.length,
             mrr: ranks.reduce((s, r) => s + (r ? 1 / r : 0), 0) / qs.length };
  }

  // ================= model prikaza =================
  // Isti oblik za snimljen i ziv odgovor, pa ih crtaju iste funkcije:
  //   { source, question, id, model, banner, variants: {A?, B?}, sources: [...] }

  const snapImg = (name) => name ? "snimljeno/img/" + name : null;

  function recordedVM(q, reason) {
    const v = (r) => ({ ans: r.ans, ms: r.ms || {}, imgs: r.att.map(snapImg), acc: r.acc });
    return {
      source: "snap", question: q.q, id: q.id, model: SNAP.model, q,
      banner: "Iz merenja " + SNAP.run + (SNAP.date ? " (" + dateSr(SNAP.date) + ")" : "") +
              ". Sistem je tada bio upaljen i odgovor je generisan uživo; sada se samo prikazuje." + (reason ? " " + reason : ""),
      variants: { A: v(q.A), B: v(q.B) },
      sources: q.ctx.map(([cid, score], i) => {
        const c = SNAP.chunks[cid];
        return { rank: i + 1, type: c.type, doc: c.doc, page: c.page, score, text: c.text,
                 img: snapImg(c.img), sentB: !!c.img && q.B.att.includes(c.img) };
      }),
    };
  }

  function liveVariant(r) {
    return { ans: r.answer || "", ms: r.latencyMs || {},
             imgs: (r.sources || []).filter((s) => s.sentToGenerator && s.imageUrl).map((s) => s.imageUrl) };
  }

  function liveVM(question, id, r) {
    return {
      source: "live", question, id, model: r.model || (SNAP && SNAP.model) || "",
      variants: { B: liveVariant(r) },
      sources: (r.sources || []).map((s) => ({
        rank: s.rank, type: s.chunkType, doc: s.documentId, page: s.page, score: s.score,
        text: s.text || "", img: s.imageUrl || null, sentB: !!s.sentToGenerator })),
    };
  }

  // ================= zajednicke komponente =================

  function citedRanks(text) {
    const s = new Set();
    ((text || "").match(/\[(\d+)\]/g) || []).forEach((m) => s.add(Number(m.slice(1, -1))));
    return s;
  }

  // opts: { scope, verdict, title, sub, pending }
  function answerCard(vm, v, opts) {
    const r = vm.variants[v];
    const card = el("article", "ans " + v.toLowerCase());
    const head = el("header");
    const vt = el("div", "vt");
    vt.append(el("b", null, opts.title || (v === "A" ? "Samo tekst" : "Tekst i slike")),
              el("small", null, opts.sub || (v === "A" ? "generator vidi opis slike umesto slike" : "uz opis dobija i originalnu sliku")));
    head.append(el("span", "vtag", v), vt);
    if (opts.verdict && r && r.acc !== null && r.acc !== undefined) {
      const good = r.acc >= OK;
      const verdict = el("span", "verdict " + (good ? "ok" : "bad"), good ? "Tačno" : "Netačno");
      verdict.title = "Ocena sudije (AnswerAccuracy); tačno je od 0,75 naviše";
      verdict.append(el("span", "sc", num(r.acc, 2)));
      head.append(verdict);
    }
    card.append(head);
    if (!r) {
      card.append(el("p", "ans-text wait", opts.pending || "Čekam odgovor sistema…"));
      return card;
    }
    const p = el("p", "ans-text");
    let last = 0;
    r.ans.replace(/\[(\d+)\]/g, (m, n, off) => {
      p.append(document.createTextNode(r.ans.slice(last, off)));
      const c = el("button", "cite", n);
      c.type = "button";
      c.title = "Izvor " + n;
      c.addEventListener("click", () => flash(opts.scope, Number(n), true));
      c.addEventListener("mouseenter", () => flash(opts.scope, Number(n), false));
      p.append(c);
      last = off + m.length;
      return m;
    });
    p.append(document.createTextNode(r.ans.slice(last)));
    const foot = el("footer");
    if (r.ms.total) foot.append(el("span", "tot", sec(r.ms.total) + " ukupno"));
    [["embed", "vektor pitanja"], ["search", "pretraga"], ["images", "slike"], ["generate", "generisanje"]]
      .forEach(([k, label]) => { if (r.ms[k] && (k !== "images" || v === "B")) foot.append(el("span", null, label + " " + sec(r.ms[k]))); });
    if (v === "B") {
      const imgs = el("span", "seen-imgs");
      imgs.title = "Slike koje je generator dobio";
      r.imgs.forEach((src) => { const i = el("img"); i.src = src; i.alt = ""; imgs.append(i); });
      foot.append(el("span", null, "poslato slika: " + r.imgs.length), imgs);
    }
    card.append(p, foot);
    return card;
  }

  // opts: { scope, variants: ["A","B"] | ["B"], expected (q iz snimka), score, title }
  function evidence(vm, opts) {
    const cites = { A: citedRanks(vm.variants.A && vm.variants.A.ans), B: citedRanks(vm.variants.B && vm.variants.B.ans) };
    const box = el("section", "evidence");
    const top = el("div", "ev-top");
    top.append(el("h2", null, opts.title || "Izvori"),
               el("p", null, opts.variants.length > 1 ? "Isti delovi u obe varijante. A vidi opis slike, B vidi opis i sliku." :
                 "Delovi dokumenata koje je pretraga vratila, redom po relevantnosti."));
    const list = el("ol", "evlist");
    vm.sources.forEach((s) => list.append(evidenceRow(s, cites, opts)));
    box.append(top, list);
    return box;
  }

  function evidenceRow(s, cites, opts) {
    const li = el("li", "ev");
    li.id = opts.scope + "-ev-" + s.rank;
    const main = el("div", "ev-main");
    const head = el("div", "ev-head");
    head.append(el("span", "pill " + s.type, TYPE[s.type] || s.type),
                el("span", "doc", s.doc + (s.page ? " · str. " + s.page : "")));
    const q = opts.expected;
    if (q && q.docs.includes(s.doc) && (!q.slika || s.type === "image")) head.append(el("span", "mark exp", "očekivani izvor"));
    opts.variants.forEach((v) => {
      if (cites[v].has(s.rank)) head.append(el("span", "mark " + v.toLowerCase(), opts.variants.length > 1 ? v + " citira" : "citiran"));
    });
    if (opts.score && typeof s.score === "number") {
      const sc = el("span", "score");
      sc.title = "Relativni skor posle min-max normalizacije (0–1); prvi je uvek 1";
      const bar = el("i");
      bar.style.setProperty("--w", Math.round(Math.max(0, Math.min(1, s.score)) * 100) + "%");
      sc.append(bar, document.createTextNode(num(s.score, 2)));
      head.append(sc);
    }
    main.append(head);
    const text = el("p", "ev-text", s.text);
    text.title = "Klikni za ceo tekst";
    text.addEventListener("click", () => text.classList.toggle("open"));
    if (s.type === "image" && s.img) {
      const wrap = el("div", "ev-img");
      const t = el("button", "thumb");
      t.type = "button";
      t.title = "Uvećaj sliku";
      const im = el("img"); im.src = s.img; im.alt = "Originalna slika iz dokumenta " + s.doc;
      t.append(im);
      t.addEventListener("click", () => openImage(s));
      const right = el("div", "views");
      if (opts.variants.includes("A")) {
        const va = el("div", "view a"); va.append(el("b", null, "A"), el("span", null, "vidi samo opis ispod")); right.append(va);
      }
      const vb = el("div", "view b");
      vb.append(el("b", null, "B"), el("span", null, s.sentB ? "vidi opis i ovu sliku" : "vidi samo opis (preko limita od 4 slike)"));
      right.append(vb, el("span", "lbl", "Opis slike"), text);
      wrap.append(t, right);
      main.append(wrap);
    } else {
      main.append(text);
    }
    li.append(el("span", "rank", String(s.rank)), main);
    return li;
  }

  function flash(scope, rank, scroll) {
    const row = $(scope + "-ev-" + rank);
    if (!row) return;
    document.querySelectorAll(".ev.hl").forEach((r) => r.classList.remove("hl"));
    row.classList.add("hl");
    if (scroll) row.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    clearTimeout(flash.t);
    flash.t = setTimeout(() => row.classList.remove("hl"), 1600);
  }

  function openImage(s) {
    $("lb-img").src = s.img;
    $("lb-img").alt = "Originalna slika iz dokumenta " + s.doc;
    $("lb-cap").textContent = s.doc + (s.page ? ", str. " + s.page : "");
    const d = $("lightbox");
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
  }
  const closeLb = () => { const d = $("lightbox"); if (d.close) d.close(); else d.removeAttribute("open"); };
  $("lb-close").addEventListener("click", closeLb);
  $("lightbox").addEventListener("click", (e) => { if (e.target === $("lightbox")) closeLb(); });

  // ================= pogled Pitaj =================

  const ask = { vm: null, compare: false, src: "live", busy: false, errA: null };

  function setStatus(kind, detail) {
    const label = { unknown: "Stanje sistema još nije provereno", ok: "Sistem odgovara uživo",
                    down: "Sistem ne odgovara", snap: "Prikazujem snimljene odgovore" }[kind];
    const box = $("sys-status");
    box.replaceChildren(el("span", "st " + (kind === "snap" ? "down" : kind), label));
    const text = detail || {
      unknown: "Vidi se posle prvog pitanja. Kad je sistem ugašen, pitanja iz skupa za evaluaciju dobijaju snimljen odgovor.",
      ok: "Odgovor stiže za 1–3 s.",
      snap: "Pitanje se ne šalje sistemu.",
    }[kind];
    if (text) box.append(el("span", null, text));
  }

  function setSource(src) {
    ask.src = src;
    $("src-live").setAttribute("aria-pressed", String(src === "live"));
    $("src-snap").setAttribute("aria-pressed", String(src === "snap"));
    setStatus(src === "snap" ? "snap" : "unknown");
  }
  $("src-live").addEventListener("click", () => setSource("live"));
  $("src-snap").addEventListener("click", () => setSource("snap"));

  function setBusy(busy) {
    ask.busy = busy;
    $("ask-btn").disabled = busy;
    document.querySelectorAll("#result .btn").forEach((b) => { b.disabled = busy; });
  }

  async function callApi(question, variant) {
    const url = $("api-url").value.trim(), key = $("api-key").value.trim();
    if (!url || !key) return { status: -1, error: "Adresa API-ja ili API ključ nisu uneti (Veza sa API-jem)." };
    store.set("apiUrl", url);
    store.set("apiKey", key);
    let resp, data = null;
    try {
      resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-api-key": key },
        body: JSON.stringify({ question, variant, retrieval: $("retrieval").value, k: 5 }),
      });
      data = await resp.json().catch(() => null);
    } catch (e) {
      return { status: 0, error: "Mrežna greška: sistem nije dostupan ili je adresa API-ja pogrešna." };
    }
    if (!resp.ok) {
      const detail = (data && (data.error || data.message)) || "";
      return { status: resp.status, error: (ERRORS[resp.status] || "Greška " + resp.status) + (detail ? " " + detail : "") };
    }
    return Object.assign({ status: 200 }, data);
  }

  function fillQuestion(text) { $("q-input").value = text; runAsk(); }

  function renderSuggest() {
    const box = $("suggest");
    const ws = words($("q-input").value);
    if (!ws.length || BY_TEXT[norm($("q-input").value)]) { box.hidden = true; return; }
    const hits = QUESTIONS.filter((q) => { const t = norm(q.q); return ws.every((w) => t.includes(w)); }).slice(0, 5);
    if (!hits.length) { box.hidden = true; return; }
    box.replaceChildren(...hits.map(suggestItem));
    box.hidden = false;
  }
  function suggestItem(q) {
    const li = el("li"), b = el("button");
    b.type = "button";
    b.append(el("span", "sid", q.id), el("span", null, q.q));
    b.addEventListener("click", () => fillQuestion(q.q));
    li.append(b);
    return li;
  }
  $("q-input").addEventListener("input", renderSuggest);
  $("q-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runAsk(); });
  $("ask-btn").addEventListener("click", runAsk);

  async function runAsk() {
    if (ask.busy) return;
    $("suggest").hidden = true;
    const text = $("q-input").value.trim();
    if (!text) { $("result").replaceChildren(el("p", "note", "Upiši pitanje ili izaberi primer.")); return; }
    const id = BY_TEXT[norm(text)];
    const snapQ = id ? SNAP_BY_ID[id] : null;
    ask.compare = false;
    ask.errA = null;

    if (ask.src === "snap") {
      if (snapQ) { ask.vm = recordedVM(snapQ); renderAsk(); }
      else renderMiss("Snimljeni odgovori postoje samo za pitanja iz skupa za evaluaciju; ovo pitanje nije među njima.", text);
      return;
    }

    ask.vm = { source: "live", question: text, id, variants: {}, sources: [] };
    renderAsk();
    setBusy(true);
    const r = await callApi(text, "B");
    setBusy(false);
    if (r.status === 200) {
      setStatus("ok");
      ask.vm = liveVM(text, id, r);
      renderAsk();
      return;
    }
    if (r.status === -1) $("conn").open = true;
    if (systemDown(r.status)) setStatus("down", r.error);
    if ((systemDown(r.status) || r.status === -1) && snapQ) {
      ask.vm = recordedVM(snapQ, r.error);
      renderAsk();
      return;
    }
    if (systemDown(r.status)) renderMiss(r.error + " Snimljen odgovor postoji samo za pitanja iz skupa za evaluaciju.", text);
    else $("result").replaceChildren(errorBanner(r.error));
  }

  function errorBanner(text) {
    const b = el("div", "banner err");
    b.append(el("b", null, "Greška"), el("span", null, text));
    return b;
  }

  function renderMiss(message, text) {
    const ws = words(text);
    const near = QUESTIONS.map((q) => [q, ws.filter((w) => norm(q.q).includes(w)).length])
      .filter(([, s]) => s > 0).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([q]) => q);
    const miss = el("div", "miss");
    miss.append(el("p", null, message));
    if (near.length) {
      const ul = el("ul", "suggest");
      near.forEach((q) => ul.append(suggestItem(q)));
      miss.append(el("span", "lbl", "Slična pitanja iz skupa"), ul);
    }
    $("result").replaceChildren(miss);
  }

  function renderAsk() {
    const vm = ask.vm;
    const parts = [];
    if (vm.source === "snap") {
      const banner = el("div", "banner");
      banner.append(el("b", null, "Snimljen odgovor"), el("span", null, vm.banner));
      parts.push(banner);
    }
    const variants = ask.compare ? ["A", "B"] : ["B"];
    const answers = el("div", "answers");
    variants.forEach((v) => answers.append(answerCard(vm, v, {
      scope: "ask",
      title: ask.compare ? undefined : "Odgovor",
      sub: ask.compare ? undefined : "varijanta B: tekst i originalne slike",
      pending: v === "A" && ask.errA ? "Varijanta A nije stigla: " + ask.errA : undefined,
    })));
    parts.push(answers);
    if (vm.variants.B) {
      const row = el("div", "result-row");
      const tog = el("button", "btn small", ask.compare ? "Sakrij varijantu A" : "Uporedi sa varijantom A (samo opis slike)");
      tog.type = "button";
      tog.addEventListener("click", toggleCompare);
      row.append(tog);
      if (vm.id && SNAP_BY_ID[vm.id]) {
        const more = el("button", "btn small", "Ovo pitanje u rezultatima merenja");
        more.type = "button";
        more.addEventListener("click", () => go(vm.id));
        row.append(more);
      }
      parts.push(row);
      if (vm.model) {
        const privacy = el("p", "privacy");
        privacy.append(el("b", null, "Privatno hostovano. "), document.createTextNode(
          "Odgovor je generisao " + vm.model.split("/").pop() + " na GPU instanci u AWS nalogu sistema" +
          (CONFIG.region ? " (" + CONFIG.region + ")" : "") + ". Pitanje i dokumenti nisu poslati nijednom spoljnom AI servisu."));
        parts.push(privacy);
      }
      if (vm.sources.length) parts.push(evidence(vm, { scope: "ask", variants, score: false }));
    }
    $("result").replaceChildren(...parts);
    setBusy(ask.busy);
  }

  async function toggleCompare() {
    if (ask.busy) return;
    if (ask.compare) { ask.compare = false; renderAsk(); return; }
    ask.compare = true;
    if (ask.vm.source === "live" && !ask.vm.variants.A) {
      ask.errA = null;
      renderAsk();
      setBusy(true);
      const r = await callApi(ask.vm.question, "A");
      setBusy(false);
      if (r.status === 200) ask.vm.variants.A = liveVariant(r);
      else ask.errA = r.error;
    }
    renderAsk();
  }

  // ================= pogled Rezultati =================

  const res = { filter: "sva", term: "", id: "N3" };
  const FILTERS = [
    ["sva", "Sva", () => true],
    ["razlika", "A ≠ B", (q) => isOk(q, "A") !== isOk(q, "B")],
    ["slika", "Samo na slici", (q) => q.slika],
    ["tesko", "Teško za opis", (q) => q.tesko],
    ["tekst", "Tekst, tabela, više", (q) => !q.slika],
    ["t-tekst", "Tekst", (q) => q.tip === "tekst"],
    ["t-tabela", "Tabela", (q) => q.tip === "tabela"],
    ["t-vise", "Više dokumenata", (q) => q.tip === "vise-dokumenata"],
    ["t-dijagram", "Dijagram", (q) => q.tip === "dijagram"],
    ["t-grafikon", "Grafikon", (q) => q.tip === "grafikon"],
  ];

  function renderSummary() {
    const Q = SNAP.questions;
    $("sum-body").replaceChildren(...GROUPS.map(([key, label, fn, sub]) => {
      const s = summarize(Q.filter(fn));
      const tr = el("tr");
      tr.setAttribute("aria-selected", String(res.filter === key));
      const b = el("button", "gbtn" + (sub ? " sub" : ""), label);
      b.type = "button";
      const td0 = el("td"); td0.append(b);
      tr.append(td0, el("td", null, String(s.n)), el("td", "ca", String(s.a)), el("td", "cb", String(s.b)),
                el("td", null, String(s.onlyA)), el("td", null, String(s.onlyB)), el("td", null, pval(s.p)),
                el("td", null, num(s.hit, 2)), el("td", null, num(s.mrr, 2)));
      tr.addEventListener("click", () => { res.filter = key; renderSummary(); renderChips(); renderList(); $("bench").scrollIntoView({ block: "start" }); });
      return tr;
    }));
    const all = summarize(Q), img = summarize(Q.filter((q) => q.slika));
    $("lede").textContent = "Varijanta B, koja uz opis vidi i originalnu sliku, tačna je na " + all.b + " od " + all.n +
      " pitanja, a A na " + all.a + ". Razlika je najveća kad je odgovor samo na slici: " + img.b + " prema " + img.a +
      " (p = " + pval(img.p) + ")." + (img.p >= 0.05 ? " Na nivou 0,05 razlika nije statistički značajna." : "");
  }

  function renderChips() {
    $("chips").replaceChildren(...FILTERS.map(([key, label, fn]) => {
      const b = el("button", "chip");
      b.type = "button";
      b.setAttribute("aria-pressed", String(res.filter === key));
      b.append(document.createTextNode(label), el("span", "n", String(SNAP.questions.filter(fn).length)));
      b.addEventListener("click", () => { res.filter = key; renderChips(); renderSummary(); renderList(); });
      return b;
    }));
  }

  function visible() {
    const fn = FILTERS.find((f) => f[0] === res.filter)[2];
    const t = res.term.trim().toLowerCase();
    return SNAP.questions.filter((q) => fn(q) && (!t || (q.id + " " + q.q + " " + q.exp).toLowerCase().includes(t)));
  }

  function renderList() {
    const items = visible();
    const list = $("qlist");
    if (!items.length) { list.replaceChildren(el("li", "empty-list", "Nijedno pitanje ne odgovara filteru.")); return; }
    list.replaceChildren(...items.map((q) => {
      const li = el("li"), b = el("button", "qi");
      b.type = "button";
      b.dataset.id = q.id;
      b.setAttribute("aria-current", String(q.id === res.id));
      const r = el("span", "qi-res");
      r.title = "A: " + (isOk(q, "A") ? "tačno" : "netačno") + " · B: " + (isOk(q, "B") ? "tačno" : "netačno");
      r.append(el("i", "dot a" + (isOk(q, "A") ? " ok" : "")), el("i", "dot b" + (isOk(q, "B") ? " ok" : "")));
      b.append(el("span", "qi-id", q.id), el("span", "qi-text", q.q), r);
      b.addEventListener("click", () => go(q.id));
      li.append(b);
      return li;
    }));
  }
  $("search").addEventListener("input", (e) => { res.term = e.target.value; if (SNAP) renderList(); });
  $("qlist").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const btns = [...$("qlist").querySelectorAll(".qi")];
    const i = btns.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = btns[Math.max(0, Math.min(btns.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
    next.focus();
    go(next.dataset.id);
  });

  function renderDetail() {
    const q = SNAP_BY_ID[res.id];
    document.querySelectorAll(".qi").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === res.id)));
    const card = el("section", "qcard");
    const meta = el("div", "qmeta");
    meta.append(el("span", "qid", q.id), el("span", "pill" + (q.slika ? " image" : q.tip === "tabela" ? " table" : ""), q.tip));
    if (q.slika) meta.append(el("span", "pill image", "odgovor samo na slici"));
    if (q.tesko) meta.append(el("span", "pill warn", "teško za opis"));
    const exp = el("div", "expected");
    exp.append(el("span", "lbl", "Očekivano"), el("span", null, q.exp), el("span", "src", "Dokument: " + q.docs.join(", ")));
    card.append(meta, el("h2", "qtext", q.q), exp);
    const vm = recordedVM(q);
    const answers = el("div", "answers");
    answers.append(answerCard(vm, "A", { verdict: true, scope: "res" }), answerCard(vm, "B", { verdict: true, scope: "res" }));
    $("detail").replaceChildren(card, answers,
      evidence(vm, { scope: "res", variants: ["A", "B"], expected: q, score: true, title: "Šta je pretraga vratila" }));
    // Izabrano pitanje u vidno polje spiska, bez pomeranja cele stranice.
    const cur = document.querySelector('.qi[aria-current="true"]'), list = $("qlist");
    if (cur) {
      const c = cur.getBoundingClientRect(), l = list.getBoundingClientRect();
      if (c.top < l.top || c.bottom > l.bottom) list.scrollTop += c.top - l.top - 60;
    }
  }

  // ================= navigacija =================
  // #pitaj, #rezultati, ili oznaka pitanja (#K3) za detalj u rezultatima.

  function show(view) {
    $("view-ask").hidden = view !== "pitaj";
    $("view-res").hidden = view !== "rezultati";
    $("tab-ask").setAttribute("aria-current", view === "pitaj" ? "page" : "false");
    $("tab-res").setAttribute("aria-current", view === "rezultati" ? "page" : "false");
  }
  function route() {
    const h = decodeURIComponent(location.hash.slice(1));
    if (SNAP && SNAP_BY_ID[h]) {
      res.id = h;
      if (!FILTERS.find((f) => f[0] === res.filter)[2](SNAP_BY_ID[h])) { res.filter = "sva"; renderChips(); renderSummary(); renderList(); }
      show("rezultati");
      renderDetail();
    } else if (h === "rezultati") {
      show("rezultati");
      if (SNAP) renderDetail();
    } else {
      show("pitaj");
    }
  }
  function go(hash) { if (location.hash.slice(1) === hash) route(); else location.hash = hash; }
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => go(t.dataset.view)));
  addEventListener("hashchange", route);

  // ================= start =================

  async function init() {
    CONFIG = (await loadJson("config.json")) || {};
    SNAP = await loadJson("snimljeno/snimljeno.json");
    if (SNAP && Array.isArray(SNAP.questions) && SNAP.questions.length) {
      SNAP_BY_ID = Object.fromEntries(SNAP.questions.map((q) => [q.id, q]));
      QUESTIONS = SNAP.questions.map((q) => ({ id: q.id, q: q.q, tip: q.tip }));
    } else {
      SNAP = null;
      QUESTIONS = ((await loadJson("pitanja.json")) || []).map((q) => ({ id: q.id, q: q.pitanje, tip: q.tip }));
    }
    BY_TEXT = Object.fromEntries(QUESTIONS.map((q) => [norm(q.q), q.id]));

    $("api-url").value = store.get("apiUrl") || CONFIG.apiUrl || "";
    $("api-key").value = store.get("apiKey");
    ["api-url", "api-key"].forEach((id) => $(id).addEventListener("change", () =>
      store.set(id === "api-url" ? "apiUrl" : "apiKey", $(id).value.trim())));

    const byId = Object.fromEntries(QUESTIONS.map((q) => [q.id, q]));
    EXAMPLES.filter((id) => byId[id]).forEach((id) => {
      const q = byId[id];
      const b = el("button", "ex", EXAMPLE_LABEL[q.tip] || q.tip);
      b.type = "button";
      b.title = q.q;
      b.addEventListener("click", () => fillQuestion(q.q));
      $("examples").append(b);
    });

    if (SNAP) {
      renderSummary();
      renderChips();
      renderList();
    } else {
      $("src-snap").disabled = true;
      $("src-snap").title = "Snimak merenja nije postavljen (evaluation/export_ui.py)";
      $("summary").replaceChildren(el("h1", null, "Rezultati merenja nisu postavljeni"),
        el("p", "note", "Snimak merenja pravi evaluation/export_ui.py, a postavlja ga deploy stack-a RagQueryStack."));
      $("bench").hidden = true;
    }
    setStatus("unknown");
    $("result").replaceChildren(el("p", "note",
      "Izaberi primer ili postavi svoje pitanje. Kad je sistem upaljen, odgovor stiže za 1–3 s."));
    route();
  }

  init();
})();
