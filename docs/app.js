"use strict";
/* KOEI × mirovinci – prikaz docs/data/latest.json (izračun radi pipeline/run.py) */

const LIM = 0.05;
const NAME = { PBZ_B: "PBZ CO B", ER_B: "Erste Plavi B", AZ_B: "AZ B", RF_B: "Raiffeisen B",
  PBZ_A: "PBZ CO A", ER_A: "Erste Plavi A", RF_A: "Raiffeisen A", AZ_A: "AZ A",
  PBZ_C: "PBZ CO C", ER_C: "Erste Plavi C", AZ_C: "AZ C", RF_C: "Raiffeisen C" };
const LINE = { PBZ_B: { c: "var(--ink)", d: "" }, ER_B: { c: "var(--under)", d: "6 4" }, AZ_B: { c: "var(--near)", d: "1.5 3.5" }, RF_B: { c: "var(--ink-3)", d: "10 3 2 3" } };
const $ = (s) => document.querySelector(s);

const fmt = (x, d = 0) => (x == null || isNaN(x)) ? "–" : x.toLocaleString("hr-HR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x, d = 2) => fmt(x * 100, d) + " %";
const eur = (x, d = 0) => fmt(x, d) + " €";
const mil = (x) => fmt(x / 1e6, 1) + " mil. €";
const dt = (iso, y = false) => { if (!iso) return "–"; const [Y, M, D] = iso.split("-"); return `${+D}. ${+M}.` + (y ? ` ${Y}.` : ""); };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let DATA = null;

async function load() {
  try {
    const r = await fetch("data/latest.json", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    DATA = await r.json();
    render(DATA);
  } catch (e) {
    $("#h1").textContent = "Podaci se nisu učitali";
    $("#lede").textContent = "Provjeri vezu i osvježi stranicu. Ako ostane ovako, dnevno osvježavanje na GitHubu nije uspjelo.";
  } finally {
    $("#app").setAttribute("aria-busy", "false");
  }
}

function render(D) {
  const B = D.fondovi.filter((f) => f.kat === "B" && f.dionica > 0);
  const over = B.filter((f) => f.status === "iznad");
  const k = D.koei;

  // traka
  $("#px").textContent = D.koei_uzivo ? eur(D.koei_uzivo.zadnja, 2) : eur(k.vwap, 2);
  const ch = D.koei_uzivo ? D.koei_uzivo.zadnja / k.zadnja - 1 : k.vwap / k.prethodni_vwap - 1;
  const chg = $("#chg"); chg.textContent = (ch >= 0 ? "+" : "") + pct(ch, 1); chg.className = "chg " + (ch < 0 ? "dn" : "up");
  const gen = new Date(D.generirano);
  $("#upd").innerHTML = `${D.koei_uzivo ? `cijena u ${D.koei_uzivo.vrijeme}` : `VWAP ${dt(k.datum)}`}<br>osvježeno ${gen.getDate()}. ${gen.getMonth() + 1}. u ${gen.toLocaleTimeString("hr-HR", { hour: "2-digit", minute: "2-digit" })}`;

  // hero – po zadnjoj cijeni (tijekom trgovanja "sada", inače zadnja zaključna); NAV ostatka portfelja s zadnjeg datuma
  const navDate = B.map((f) => f.nav_date).sort().pop() || k.datum;
  const L = D.koei_uzivo;
  const pc = L ? L.zadnja : k.zadnja;
  const pcLbl = L ? `cijenu sada (${L.vrijeme}, ${eur(pc, 2)})` : `zadnju zaključnu cijenu (${dt(k.datum)}, ${eur(pc, 2)})`;
  const S0 = scenario(pc);
  const sellers = S0.rows.filter((x) => x.n5 > 0).sort((a, b) => b.n5 - a.n5);
  const marF = B.filter((f) => f.dionica_izvor.startsWith("MAR"));
  const lagF = B.filter((f) => f.dionica_trg && f.dionica_trg < f.nav_date && f.status === "iznad" && !marF.includes(f));
  const lagD = lagF.length ? lagF.map((f) => f.dionica_trg).sort()[0] : null;
  const az = B.find((f) => f.id === "AZ_B");
  const minPrag = Math.min(...B.filter((f) => f.dionica > 0 && f.prag_cijena).map((f) => f.prag_cijena));
  $("#h1").innerHTML = sellers.length
    ? `Uz ${L ? "cijenu sada" : "zadnju cijenu"} mirovinci moraju prodati još <span class="big">${fmt(S0.t5)}</span> dionica KOEI`
    : "Uz zadnju cijenu nijedan fond ne mora prodavati KOEI";
  const rows = sellers.map((x) => `<li><span>${NAME[x.id]}</span><b>${fmt(x.n5)}</b><small>${mil(x.n5 * pc)}, udio ${pct(x.w)}</small></li>`);
  if (az && !sellers.some((x) => x.id === "AZ_B")) rows.push(`<li class="zero"><span>AZ B</span><b>0</b><small>počinje prodavati tek iznad ${eur(az.prag_cijena, 1)}</small></li>`);
  $("#lede").innerHTML = (sellers.length
    ? `<p>To je najmanje koliko trebaju prodati da im KOEI padne na 5 % neto imovine fonda (zakonski limit), uz ${pcLbl}: ${mil(S0.t5 * pc)} ili ${pct(S0.t5 / D.shares_out, 1)} Končara. Ako se spuste na 4,9 %, kao PBZ CO u prosincu 2025., to je ${fmt(S0.t49)} dionica.</p>`
    : `<p>Ispod ${eur(minPrag, 1)} nitko ne mora prodavati; zadnja cijena je ${eur(pc, 2)}.</p>`)
    + `<ul class="split">${rows.join("")}</ul>`
    + `<p class="small">NAV fondova od ${dt(navDate, true)}; pozicije iz SKDD-a${marF.length ? `, a za ${marF.map((f) => NAME[f.id]).join(" i ")} iz obavijesti o transakcijama na ZSE (trgovine do ${dt(marF[0].dionica_trg, true)})` : ""}${lagD ? `${marF.length ? "; za ostale" : ""} za trgovine do ${dt(lagD, true)} Ako su prodavali nakon toga, to se još ne vidi (SKDD kasni 2 radna dana) i ostatak je manji.` : "."} Broj se mijenja s cijenom – tablica ispod.</p>`;
  const ageH = (Date.now() - new Date(D.generirano)) / 36e5;
  const staleNav = B.filter((f) => f.nav_date < navDate && !f.id.startsWith("PBZ")).map((f) => `${NAME[f.id]} (${dt(f.nav_date)})`);
  const warn = [];
  if (ageH > 30) warn.push(`Podaci nisu osvježeni od ${dt(D.generirano.slice(0, 10), true)} – provjeri GitHub Actions.`);
  if (staleNav.length) warn.push(`Stariji NAV: ${staleNav.join(", ")}.`);
  if (D.moguca_podjela) warn.push("Cijena KOEI promijenila se u jednom danu više od 50 % – moguća podjela dionica; brojke treba provjeriti.");
  if (warn.length) $(".hero").insertAdjacentHTML("beforeend", `<div class="warn">${warn.map(esc).join(" ")}</div>`);
  const tiles = [
    ["", eur(minPrag, 1), "ispod te cijene nitko ne mora prodavati"],
    ["", az ? eur(az.prag_cijena, 1) : "–", "iznad te cijene prodaje i AZ B (398 tis. dionica)"],
    ["", fmt(S0.t5 / D.likvidnost.adv20.dionica, 0) + " dana", `ukupnog dnevnog prometa KOEI (${fmt(D.likvidnost.adv20.dionica)} dionica dnevno)`],
  ];
  $("#totals").innerHTML = tiles.map(([c, b, s]) => `<div class="tot ${c}"><b>${b}</b><span>${s}</span></div>`).join("");

  renderPrices(D, B);
  renderGauges(B);
  initCalc();
  renderChart(180);
  renderEvents(D);
  renderBlocks(D);
  renderCal(D);
  renderOthers(D);
  renderMethod(D);
  $("#foot").innerHTML = `Osobni alat za praćenje, ne savjet za ulaganje. Izvori: ZSE, SKDD (preko MojeDionice), NAV sa stranica AZ, Erste Plavi, PBZ CO i Raiffeisen, obavijesti o transakcijama PBZ CO (eho.zse.hr). Podaci kasne 1–2 radna dana.`;
}

// ---------------------------------------------------------------- količine po cijeni
function renderPrices(D, B) {
  const k = D.koei, L = D.koei_uzivo;
  const hold = B.filter((f) => f.dionica > 0 && f.prag_cijena && f.prag_cijena < 3 * f.vwap).sort((a, b) => a.prag_cijena - b.prag_cijena);
  const navDate = B.map((f) => f.nav_date).sort().pop();
  if (!hold.length) { $("#ladder").innerHTML = ""; return; }
  const min = hold[0];
  const cur = L ? L.zadnja : k.zadnja;
  const state = cur < min.prag_cijena ? `Uz sadašnju cijenu (${eur(cur, 2)}) nitko ne mora prodavati.`
    : `Uz sadašnju cijenu (${eur(cur, 2)}) prodaju ${hold.filter((f) => cur >= f.prag_cijena).map((f) => NAME[f.id]).join(" i ")}.`;
  $("#ladder").innerHTML = `<p class="floor">Ispod <b>${eur(min.prag_cijena, 1)}</b> nitko ne mora prodavati.</p>
    <ol class="steps">${hold.map((f) => `<li><span>od <b>${eur(f.prag_cijena, 1)}</b></span><span>prodaje ${NAME[f.id]}</span></li>`).join("")}</ol>
    <p class="state">${state}</p>`;
  $("#px-note").textContent = `Količine do 5 % NAV-a po fondu. Pozicije su sve prodaje koje SKDD već pokazuje, a NAV je od ${dt(navDate, true)}; tablica se osvježava svaki sat tijekom trgovanja.`;
  // sažeta tablica (~8 redaka): pragovi fondova, sadašnja cijena i okrugle cijene po 50 € između; ostalo na klik
  const curRow = L ? { c: L.zadnja, t: `sada (${L.vrijeme})`, cls: "now" } : { c: k.zadnja, t: `zadnja zaključna (${dt(k.datum)})`, cls: "now" };
  const special = [curRow, ...hold.map((f) => ({ c: f.prag_cijena, t: `ovdje počinje ${NAME[f.id]}`, cls: "trig" }))];
  const far = (c) => special.every((r) => Math.abs(r.c - c) > 15);
  const top = Math.max(cur, hold.at(-1).prag_cijena) + 100;
  const grid50 = [], grid25 = [];
  for (let c = Math.ceil(min.prag_cijena / 50) * 50; c <= top; c += 50) if (far(c)) grid50.push({ c, t: "", cls: "" });
  for (let c = Math.floor(min.prag_cijena * 0.97 / 25) * 25; c <= top + 50; c += 25) if (far(c) && c % 50) grid25.push({ c, t: "", cls: "extra" });
  const rows = [...special, ...grid50, ...grid25].sort((a, b) => a.c - b.c);
  const ids = ["PBZ_B", "ER_B", "AZ_B"].filter((id) => B.some((f) => f.id === id));
  $("#pxtbl").innerHTML = `<thead><tr><th>Cijena</th>${ids.map((id) => `<th>${NAME[id]}</th>`).join("")}<th>Ukupno</th><th>mil. €</th><th>do 4,9 %</th></tr></thead><tbody>` +
    rows.map((r) => {
      const s = scenario(r.c), by = Object.fromEntries(s.rows.map((x) => [x.id, x.n5]));
      return `<tr class="${r.cls}"${r.cls === "extra" ? " hidden" : ""}><td><b>${eur(r.c, r.t ? 2 : 0)}</b>${r.t ? `<small>${esc(r.t)}</small>` : ""}</td>${ids.map((id) => `<td>${by[id] ? fmt(by[id]) : "–"}</td>`).join("")}<td><b>${s.t5 ? fmt(s.t5) : "0"}</b></td><td>${s.t5 ? fmt(s.t5 * r.c / 1e6, 1) : "–"}</td><td>${s.t49 ? fmt(s.t49) : "–"}</td></tr>`;
    }).join("") + "</tbody>";
  if (!$("#px-more")) {
    const btn = document.createElement("button"); btn.id = "px-more"; btn.className = "more"; btn.type = "button"; btn.textContent = "Prikaži cijene po 25 €";
    btn.onclick = () => { document.querySelectorAll("#pxtbl tr.extra").forEach((tr) => (tr.hidden = !tr.hidden)); btn.textContent = btn.textContent.includes("Prikaži") ? "Sakrij cijene po 25 €" : "Prikaži cijene po 25 €"; };
    $("#pxtbl").closest(".tbl-wrap").after(btn);
  }
  $("#px-foot").textContent = "Fond prodaje samo kad mu je udio iznad 5 %. Za sve cijene vrijedi isti NAV ostatka portfelja; NAV raste samo s vrijednošću vlastite pozicije KOEI. Fondovi vrednuju KOEI po dnevnom VWAP-u, pa je stvarni prag dana onaj po VWAP-u.";
}

// ---------------------------------------------------------------- mjerila
function renderGauges(B) {
  const max = Math.max(0.065, ...B.map((f) => f.udio + 0.004));
  const x = (v) => (v / max) * 100;
  $("#limit-note").textContent = "Crta je zakonski limit (ZOMF čl. 127.). Šrafirani dio preko crte je višak iznad 5 %. Rok za usklađenje je najviše 3 mjeseca, uz moguće produljenje HANFA-e.";
  $("#gauges").innerHTML = B.sort((a, b) => b.udio - a.udio).map((f, i) => {
    const fill = Math.min(f.udio, LIM), extra = Math.max(0, f.udio - LIM);
    const facts = [];
    if (f.status === "iznad") {
      facts.push(`<span class="x">višak <b>${fmt(f.visak5)}</b> dionica uz VWAP ${dt(f.nav_date)} (${eur(f.vwap, 2)})</span>`);
      facts.push(`<span>iznad od <b>${f.iznad_od_pocetak_povijesti ? "≤ " : ""}${dt(f.iznad_od)}</b>, ${f.iznad_dana} trg. dana</span>`);
      const rani = f.rok_3m_rani && f.rok_3m_rani !== f.rok_3m ? dt(f.rok_3m_rani) + "–" : "";
      facts.push(`<span>rok ~<b>${rani}${dt(f.rok_3m)}</b> <button class="info" type="button" aria-label="Kako se procjenjuje rok" data-tip="Procjena: 3 mjeseca od zadnjeg prelaska 5 % (ZOMF čl. 135.).${rani ? ` Raniji datum vrijedi ako se kratki padovi do 0,02 postotna boda ispod 5 % ne računaju kao prekid.` : ""} HANFA može produljiti za još 3 mjeseca (~${dt(f.rok_6m, true)}). Zakon ne kaže od kojeg se dana računa; 2024./25. oba su fonda bila iznad 5 % dulje od 3 mjeseca.">?</button></span>`);
    } else {
      const big = f.prag_cijena > 2.5 * f.vwap;
      facts.push(`<span>prelazi 5 % kod <b>${big ? "> " + eur(2.5 * f.vwap) : eur(f.prag_cijena, 1)}</b>${big ? "" : ` (+${pct(f.prag_cijena / f.vwap - 1, 1)} od VWAP-a ${dt(f.nav_date)})`}</span>`);
      if (f.nedavno_iznad && f.nedavno_iznad.length) facts.push(`<span>bio iznad 5 %: <b>${f.nedavno_iznad.map((d) => dt(d)).join(", ")}</b> (bez prodaje)</span>`);
    }
    facts.push(`<span><b>${fmt(f.dionica)}</b> dionica, ${pct(f.posto_izdanja, 1)} Končara</span>`);
    const chg = f.zadnja_promjena ? `Zadnja promjena ${dt(f.zadnja_promjena.trg, true)}: ${f.zadnja_promjena.delta > 0 ? "+" : ""}${fmt(f.zadnja_promjena.delta)} dionica.` : "Bez promjene pozicije.";
    const src = esc(f.dionica_izvor.replace(/ \(namira.*\)/, "").replace("SKDD via MojeDionice", "SKDD preko MojeDionice"));
    return `<div class="g" data-s="${f.status}" role="listitem">
      <div class="g-top"><div class="g-pct">${pct(f.udio)}</div><div class="g-name">${NAME[f.id]}<small>NAV ${fmt(f.nav / 1e9, 2)} mlrd. €</small></div></div>
      <div class="track" aria-hidden="true">
        <div class="fill" style="width:${x(fill)}%"></div>
        ${extra ? `<div class="over" style="left:${x(LIM)}%;width:${x(extra)}%"></div>` : ""}
        <div class="line5" style="left:calc(${x(LIM)}% - 1px)"></div>
        ${i === 0 ? `<span class="line5-lbl" style="left:${x(LIM)}%">5 %</span>` : ""}
      </div>
      <div class="g-facts">${facts.join("")}</div>
      <div class="g-src">Pozicija na dan trgovanja ${dt(f.dionica_trg, true)}${f.dionica_tocno ? "" : " (procjena)"}, ${src}. ${chg} NAV od ${dt(f.nav_date, true)}${f.nav_procjena ? " – procjena prema kretanju ostalih fondova (stranica društva nije dohvaćena)." : ""}</div>
    </div>`;
  }).join("");
}

// ---------------------------------------------------------------- kalkulator
function scenario(c, target = LIM) {
  const rows = [];
  let t5 = 0, t49 = 0;
  for (const f of DATA.fondovi.filter((f) => f.kat === "B" && f.dionica > 0)) {
    const nv = f.nav + f.dionica * (c - f.vwap);
    const w = f.dionica * c / nv;
    const n5 = w > LIM ? f.dionica - LIM * nv / c : 0, n49 = w > LIM ? f.dionica - 0.049 * nv / c : 0;
    rows.push({ id: f.id, w, n5, n49 });
    t5 += n5; t49 += n49;
  }
  return { rows, t5, t49 };
}

function initCalc() {
  const s = $("#slider");
  s.min = Math.floor(DATA.koei.vwap * 0.8); s.max = Math.ceil(DATA.koei.vwap * 1.45);
  $(".calc-scale").innerHTML = `<span>${eur(+s.min)}</span><span>${eur(+s.max)}</span>`;
  s.step = "any"; s.value = DATA.koei.vwap;
  const upd = () => {
    const c = +s.value, r = scenario(c), base = DATA.koei.vwap;
    $("#calc-px").textContent = eur(c, Math.abs(c - DATA.koei.vwap) < 0.005 ? 2 : 0);
    $("#calc-delta").textContent = `${c >= base ? "+" : ""}${pct(c / base - 1, 1)} od VWAP-a ${dt(DATA.koei.datum)}`;
    s.setAttribute("aria-valuetext", eur(c));
    const adv = DATA.likvidnost.adv20.dionica;
    $("#calc-out").innerHTML = `<table>${r.rows.sort((a, b) => b.n5 - a.n5).map((x) =>
      `<tr><td>${NAME[x.id]} <span style="color:var(--ink-3)">${pct(x.w)}</span></td><td>${x.n5 ? fmt(x.n5) : "–"}</td></tr>`).join("")}
      <tr class="sum"><td>Ukupno do 5 %</td><td>${fmt(r.t5)} dionica</td></tr></table>
      <p class="sub">${mil(r.t5 * c)}, ${pct(r.t5 / DATA.shares_out, 2)} Končara, ${fmt(r.t5 / adv, 0)} dana prometa. Do 4,9 %: ${fmt(r.t49)} dionica. NAV se mijenja s vlastitom pozicijom KOEI; ostatak portfelja nepromijenjen.</p>`;
  };
  s.oninput = upd; upd();
}

// ---------------------------------------------------------------- graf
function renderChart(days) {
  const H = DATA.povijest, ids = ["PBZ_B", "ER_B", "AZ_B", "RF_B"].filter((id) => H.series[id]);
  const n = H.dates.length, from = Math.max(0, n - Math.round(days * 0.69));   // ~trg. dani
  const idx = []; for (let i = from; i < n; i++) if (ids.some((id) => H.series[id][i] != null)) idx.push(i);
  const W = Math.max(300, Math.round($("#chart").clientWidth || 720)), Hh = Math.round(Math.min(340, Math.max(230, W * 0.56))), m = { l: 34, r: 34, t: 12, b: 24 };
  const vals = idx.flatMap((i) => ids.map((id) => H.series[id][i]).filter((v) => v != null && v > 2));
  const yMin = Math.min(4, Math.floor(Math.min(...vals) * 2) / 2), yMax = Math.max(6, Math.ceil(Math.max(...vals) * 2) / 2);
  const X = (k) => m.l + (k / Math.max(1, idx.length - 1)) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - yMin) / (yMax - yMin)) * (Hh - m.t - m.b);
  let g = "";
  for (let v = yMin; v <= yMax + 1e-9; v += 0.5) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--rule)" stroke-width="${v === 5 ? 0 : 1}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${fmt(v, 1)}</text>`;
  // mjeseci
  let lastM = "";
  idx.forEach((i, k) => { const mo = H.dates[i].slice(0, 7); if (mo !== lastM) { lastM = mo; if (k > 0) g += `<text x="${X(k)}" y="${Hh - 6}" font-size="11" fill="var(--ink-3)">${+mo.slice(5)}/${mo.slice(2, 4)}</text>`; } });
  // objave rezultata
  const res = (DATA.rezultati.svi || []).map((r) => r[0]);
  idx.forEach((i, k) => { if (res.includes(H.dates[i])) g += `<line x1="${X(k)}" x2="${X(k)}" y1="${m.t}" y2="${Hh - m.b}" stroke="var(--ink-3)" stroke-dasharray="2 3"/>`; });
  // limit
  g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(5)}" y2="${Y(5)}" stroke="var(--limit)" stroke-width="2"/><text x="${W - m.r + 4}" y="${Y(5) + 4}" font-size="12" font-weight="600" fill="var(--limit)">5 %</text>`;
  for (const id of ids) {
    let d = "", pen = false;
    idx.forEach((i, k) => { const v = H.series[id][i]; if (v == null || v < yMin) { pen = false; return; } d += (pen ? "L" : "M") + X(k).toFixed(1) + " " + Y(v).toFixed(1); pen = true; });
    g += `<path d="${d}" fill="none" stroke="${LINE[id].c}" stroke-width="2" stroke-dasharray="${LINE[id].d}" stroke-linejoin="round"/>`;
  }
  g += `<line id="cx" x1="0" x2="0" y1="${m.t}" y2="${Hh - m.b}" stroke="var(--ink)" stroke-width="1" opacity="0"/>`;
  $("#chart").innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Dnevni udio KOEI u NAV-u fondova B">${g}<rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${Hh}" fill="transparent" id="hit"/></svg>`;
  const shown = ids.filter((id) => idx.some((i) => H.series[id][i] != null && H.series[id][i] >= yMin));
  $("#legend").innerHTML = shown.map((id) => `<span><i style="border-top-style:${LINE[id].d ? (LINE[id].d.startsWith("1.5") ? "dotted" : "dashed") : "solid"};border-color:${LINE[id].c}"></i>${NAME[id]}</span>`).join("") + `<span><i style="border-top-style:solid;border-color:var(--limit)"></i>limit</span>`;
  const svg = $("#chart svg"), tip = $("#tip"), cx = svg.querySelector("#cx");
  const move = (ev) => {
    const p = ev.touches ? ev.touches[0] : ev, r = svg.getBoundingClientRect();
    const sx = (p.clientX - r.left) * (W / r.width), k = Math.max(0, Math.min(idx.length - 1, Math.round((sx - m.l) / (W - m.l - m.r) * (idx.length - 1))));
    const i = idx[k]; cx.setAttribute("x1", X(k)); cx.setAttribute("x2", X(k)); cx.setAttribute("opacity", ".35");
    tip.hidden = false;
    tip.innerHTML = `<b>${dt(H.dates[i], true)}</b>, VWAP ${eur(H.vwap[i], 2)}<br>` + ids.map((id) => `${NAME[id]}: ${H.series[id][i] == null ? "–" : fmt(H.series[id][i], 2) + " %"}${H.approx[id][i] ? " *" : ""}`).join("<br>") + (ids.some((id) => H.approx[id][i]) ? "<br><small>* procjena (pozicija iz mjesečnog izvješća ili procijenjeni NAV)</small>" : "");
    const tx = Math.min(window.innerWidth - 250, p.clientX + 12); tip.style.left = tx + "px"; tip.style.top = (p.clientY - 10 - tip.offsetHeight) + "px";
  };
  const leave = () => { tip.hidden = true; cx.setAttribute("opacity", "0"); };
  const hit = svg.querySelector("#hit");
  hit.addEventListener("pointermove", move); hit.addEventListener("pointerleave", leave); hit.addEventListener("touchmove", move, { passive: true }); hit.addEventListener("touchend", leave);
}
document.querySelectorAll(".range button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".range button").forEach((x) => x.setAttribute("aria-pressed", x === b)); renderChart(+b.dataset.r);
}));

// ---------------------------------------------------------------- događaji
function renderEvents(D) {
  // uzastopne promjene istog fonda (razmak do 10 dana) spajaju se u jedan val
  const ev = [], lastOf = {};
  for (const e of D.dogadaji.filter((e) => ["prodaja", "kupnja", "abb", "razlika", "rezultati"].includes(e.vrsta))) {
    const g = (e.vrsta === "prodaja" || e.vrsta === "kupnja") && lastOf[e.fond + e.vrsta];
    if (g && (new Date(g.od) - new Date(e.datum)) / 864e5 <= 10) {
      g.od = e.datum; g.dionica += e.dionica; g.dana += 1; g.eur += Math.abs(e.dionica) * (e.cijena || 0);
    } else {
      const n = { ...e, do: e.datum, od: e.datum, dana: 1, eur: Math.abs(e.dionica || 0) * (e.cijena || 0) };
      ev.push(n); if (e.fond) lastOf[e.fond + e.vrsta] = n;
    }
  }
  const src = (s) => esc(s.replace(/ \(namira.*\)/, "").replace("SKDD via MojeDionice", "SKDD preko MojeDionice"));
  const li = (e) => {
    if (e.fond) {
      if (e.vrsta === "razlika") return `<li><time>${dt(e.do, true)}</time><div><b>${NAME[e.fond]}</b>: ${fmt(e.dionica)} dionica<span class="meta">Razlika između obavijesti i mjesečnog portfelja fonda, bez poznatog datuma trgovanja.</span></div></li>`;
      if (e.vrsta === "abb") return `<li class="sell"><time>${dt(e.do, true)}</time><div><b>${NAME[e.fond]}</b> prodao <span class="q">${fmt(Math.abs(e.dionica))}</span> dionica ubrzanim prikupljanjem ponuda<span class="meta">${esc(e.opis || "")}. Stanje nakon ${fmt(e.stanje)}.</span></div></li>`;
      const rijec = e.vrsta === "prodaja" ? "prodajom" : "kupnjom";
      const per = e.dana > 1 ? `${dt(e.od)}–${dt(e.do, true)}, ${e.dana} dana s ${rijec}` : dt(e.do, true);
      return `<li class="${e.vrsta === "prodaja" ? "sell" : ""}"><time>${dt(e.do, true)}</time><div><b>${NAME[e.fond]}</b> ${e.vrsta === "prodaja" ? "prodao" : "kupio"} <span class="q">${fmt(Math.abs(e.dionica))}</span> dionica<span class="meta">${per}; stanje nakon ${fmt(e.stanje)}${e.eur ? `; ~${mil(e.eur)} po VWAP-u` : ""}. ${src(e.izvor)}.</span></div></li>`;
    }
    return `<li><time>${dt(e.datum, true)}</time><div class="mark">${esc(e.tekst)}</div></li>`;
  };
  const all = ev.map(li), first = 10;
  $("#events").innerHTML = all.slice(0, first).join("");
  if (all.length > first) {
    const b = document.createElement("button"); b.className = "more"; b.type = "button"; b.textContent = `Prikaži još ${all.length - first}`;
    b.onclick = () => { $("#events").innerHTML = all.join(""); b.remove(); };
    $("#events").after(b);
  }
}

function renderBlocks(D) {
  const rows = D.blokovi.slice(0, 12);
  $("#blocks").innerHTML = `<thead><tr><th>Datum</th><th>Dionica</th><th>Cijena</th><th>mil. €</th></tr></thead><tbody>` +
    (rows.length ? rows.map((b) => `<tr><td>${dt(b.date, true)}</td><td>${fmt(b.dionica)}</td><td>${eur(b.cijena, 2)}</td><td>${fmt(b.eur / 1e6, 2)}</td></tr>`).join("") : `<tr><td colspan="4">Nema blokova.</td></tr>`) + "</tbody>";
}

function renderCal(D) {
  const r = D.rezultati, today = new Date().toISOString().slice(0, 10);
  const items = [
    [r.zadnji[0], `Rezultati ${r.zadnji[1]} objavljeni. U ciklusima FY 2025, Q1 i H1 2026. PBZ CO je počinjao prodaju 0–1 trgovinski dan nakon objave.`],
    [D.gs[0], `${D.gs[1]}. Ako bude izabrana, Erste Plavi fondovi trebali bi javno prijavljivati transakcije KOEI (MAR čl. 19.).`],
    [r.zatvoreno_od, "Približni početak razdoblja od 30 dana prije sljedećih rezultata – PBZ CO dosad u tom razdoblju nije prodavao."],
    [r.sljedeci[0], `Sljedeći rezultati, ${r.sljedeci[1]}.`],
  ].sort((a, b) => a[0].localeCompare(b[0]));
  const nxt = items.find(([d]) => d >= today);
  $("#cal").innerHTML = items.map(([d, t]) => `<li><time class="${nxt && d === nxt[0] ? "now" : ""}">${dt(d, true)}</time><span>${esc(t)}</span></li>`).join("");
}

function renderOthers(D) {
  const rows = D.fondovi.filter((f) => f.kat !== "B");
  $("#others").innerHTML = `<thead><tr><th>Fond</th><th>Dionica</th><th>Stanje na</th><th>Udio u NAV-u</th><th>Prelazi limit kod</th></tr></thead><tbody>` +
    rows.map((f) => `<tr><td>${NAME[f.id]}</td><td>${f.dionica ? fmt(f.dionica) : "–"}</td><td>${f.dionica_trg ? dt(f.dionica_trg, true) : "–"}</td><td>${f.dionica ? pct(f.udio) : "ne drži"}</td><td>${f.prag_cijena ? (f.prag_cijena > 2.5 * f.vwap ? "> " + eur(2.5 * f.vwap) : eur(f.prag_cijena)) : "–"}</td></tr>`).join("") + "</tbody>";
}

function renderMethod(D) {
  const st = Object.entries(D.izvori_status || {});
  const bad = st.filter(([, v]) => !String(v).startsWith("ok"));
  // PBZ CO NAV s GitHuba nije dostupan (poznato); procjena se označava tiho u kartici fonda
  const realBad = bad.filter(([k]) => !k.startsWith("NAV PBZ"));
  if (realBad.length) $(".hero").insertAdjacentHTML("beforeend", `<div class="warn">Zadnje osvježavanje nije dohvatilo: ${realBad.map(([k]) => esc(k)).join(", ")}. Prikazani su zadnji dostupni podaci.</div>`);
  $("#method").innerHTML = `
  <p><b>Limit.</b> Obvezni mirovinski fond A ili B smije u dionice jednog izdavatelja uložiti najviše 5 % neto imovine (ZOMF čl. 127. st. 2.; C: 3 %). Kad udio prijeđe limit bez kupnje (rast cijene ili pad ostatka portfelja – prema uobičajenom tumačenju čl. 135. st. 2.), fond ga mora uskladiti u razumnom roku, najviše 3 mjeseca, uz moguće produljenje HANFA-e za još 3. Grupa KOEI + KODT smije najviše 10 %. Vlasnički limiti (20 % po fondu) ne ovise o cijeni.</p>
  <p><b>Izračun.</b> Udio = broj dionica × dnevni VWAP kontinuiranog trgovanja na ZSE (bez blokova i OTC-a) ÷ dnevni NAV fonda. Fondovi vrednuju KOEI po tom VWAP-u (provjereno za PBZ CO, AZ i Erste na više krajeva mjeseci, uključujući dane s blok-transakcijama). Višak = dionice − 5 % × NAV ÷ VWAP. Kod scenarija i praga cijene NAV raste zajedno s vlastitom pozicijom KOEI.</p>
  <ul>
    <li><b>Pozicije</b>: SKDD preko MojeDionice (prvih 5 dioničara, po datumu trgovanja T, vidljivo T+2). PBZ CO prijavljuje transakcije jer je predsjednica Uprave članica NO Končara (MAR čl. 19.); obavijesti se dva puta dnevno preuzimaju s eho.zse.hr (skenirane čita OCR) i prihvaćaju samo ako se retci slažu sa zbirnim volumenom i prosječnom cijenom iz iste obavijesti. Transakcije nakon zadnjeg SKDD stanja odmah ulaze u izračun; kad SKDD stigne, svaka promjena mora odgovarati zbroju obavijesti (inače je izvor označen kao greška). Pozicije označene kao procjena izvedene su iz mjesečnih izvješća (±0,2 %).</li>
    <li><b>NAV</b>: dnevno sa stranica AZ, Erste Plavi, PBZ CO i Raiffeisen; na krajevima mjeseci jednak HANFA-inom.</li>
    <li><b>Cijene</b>: ZSE REST, kontinuirano trgovanje i blokovi odvojeno.</li>
    <li><b>Što se ne vidi</b>: transakcije zadnja 2 radna dana; Raiffeisen B i fondovi A nisu među prvih 5 dioničara, pa je njihova pozicija ručno upisana iz zadnjeg izvješća (datum u tablici). Promjena među dioničarima 6–10 javlja se obaviješću. Fondovi prekoračenja ne objavljuju pravovremeno, tek naknadno u godišnjim izvješćima.</li>
  </ul>
  <p><b>Stanje izvora pri zadnjem osvježavanju:</b> ${st.map(([k, v]) => `${esc(k)} <span class="${String(v).startsWith("ok") ? "ok" : "bad"}">${String(v).startsWith("ok") ? "ok" : "greška"}</span>`).join(", ")}.</p>`;
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-tip]"), tip = $("#tip");
  if (!t) { if (!e.target.closest("#chart")) tip.hidden = true; return; }
  tip.textContent = t.dataset.tip; tip.hidden = false;
  const r = t.getBoundingClientRect(); tip.style.left = Math.max(8, Math.min(window.innerWidth - 250, r.left - 100)) + "px"; tip.style.top = (r.bottom + 8) + "px";
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
load();
let _rz; window.addEventListener("resize", () => { clearTimeout(_rz); _rz = setTimeout(() => { if (DATA) { const b = document.querySelector('.range button[aria-pressed="true"]'); renderChart(b ? +b.dataset.r : 180); } }, 150); });
