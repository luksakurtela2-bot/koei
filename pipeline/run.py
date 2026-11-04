"""KOEI × obvezni mirovinski fondovi – dnevni izračun limita 5 % NAV-a (ZOMF čl. 127. st. 2.).

    python pipeline/run.py            # dohvat + izračun → docs/data/latest.json, data/obavijest.txt
    python pipeline/run.py --offline  # samo izračun iz postojećih CSV-ova u data/

Metodologija (analiza 3.11.2026., notes/06 i 08):
  udio = dionice × dnevni VWAP kontinuiranog trgovanja (samo CT; bez blokova i OTC-a) ÷ dnevni NAV fonda
  dionice: SKDD preko MojeDionice (po datumu trgovanja T, vidljivo T+2), izvješća fondova; nakon zadnjeg SKDD stanja
           pribrajaju se MAR obavijesti fondova s eho.zse.hr (PBZ CO; provjerene prema zbirnom volumenu i cijeni)
  višak = dionice − cilj × NAV(c) ÷ c,  NAV(c) = NAV + dionice × (c − VWAP)   (ostatak portfelja nepromijenjen)
"""
import csv, json, sys
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
D = APP / "data"                 # radni CSV-ovi (ne objavljuju se na stranici)
OUT = APP / "docs" / "data"      # latest.json za stranicu
sys.path.insert(0, str(APP / "pipeline"))
import sources as S
import mojedionice as MD
import eho as E

LIMIT, LIMIT_C = 0.05, 0.03
# Podjela dionica: upisati (prvi dan trgovanja novim dionicama, omjer) kad ZSE objavi, npr. ("2027-01-11", 10).
# Prije upisa: provjeriti vraća li ZSE REST povijest već prilagođenu (tada ovdje ništa ne mijenjati za cijene).
SPLITS = {"KOEI": [], "KODT": []}
SHARES_OUT_0 = {"KOEI": 2_572_119, "KODT": 388_376}
MD_MAP = {"AZ OMF KATEGORIJE B": "AZ_B", "PBZ CO OMF - KATEGORIJA B": "PBZ_B", "ERSTE PLAVI OMF KATEGORIJE B": "ER_B",
          "RAIFFEISEN OMF KATEGORIJE B": "RF_B", "PBZ CO OMF - KATEGORIJA A": "PBZ_A", "AZ OMF KATEGORIJE A": "AZ_A",
          "ERSTE PLAVI OMF KATEGORIJE A": "ER_A", "RAIFFEISEN OMF KATEGORIJE A": "RF_A"}
# objave rezultata Končara (ZSE EHO); sljedeća je procjena prema 2024.–2026. – ažurirati kad Končar objavi kalendar 2027.
RESULTS = [("2025-10-29", "Q3 2025"), ("2026-02-26", "FY 2025"), ("2026-04-29", "Q1 2026"), ("2026-07-30", "H1 2026"), ("2026-10-29", "Q3 2026")]
NEXT_RESULTS = ("2027-02-26", "FY 2026 (procjena)")
ABB = {("2025-12-03", "PBZ_B"): "ABB (InterCapital) 35.593 dionica po 650 €, cilj ~4,9 % NAV-a"}
GS = ("2026-12-10", "Izvanredna GS Končara: podjela dionica 1:10 i izbor N. Ivanović (članica uprave Erste d.o.o.) u NO")
TRACK = ["PBZ_B", "ER_B", "AZ_B", "RF_B", "PBZ_A", "ER_A", "RF_A", "AZ_A"]
NO_KOEI = ["AZ_C", "ER_C", "PBZ_C", "RF_C"]
MUST_SEE = {"AZ_B", "PBZ_B", "ER_B"}   # moraju biti među prvih 5 na MojeDionicama
OK = {"da", "razlika", "mar"}        # pozicije iz stvarnih transakcija (ne izvedene iz mjesečnih izvješća)
MAR_OD = "2025-11-01"                 # MAR obavijesti fondova (eho.zse.hr) prate se od ovog datuma objave


# ================================================================ pomoćno
def read_csv(p):
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def write_csv(p, header, rows):
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def add_months(iso, n):
    import calendar
    d = date.fromisoformat(iso); m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def zagreb_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Zagreb"))
    except Exception:          # Windows bez tzdata: CET/CEST približno
        u = datetime.now(timezone.utc)
        dst = 3 < u.month < 11 or (u.month == 3 and u.day >= 25) or (u.month == 10 and u.day < 25)
        return u + timedelta(hours=2 if dst else 1)


def sf(sym, d):
    """Koliko novih dionica vrijedi jedna stara na datum d (1 nakon podjele)."""
    k = 1
    for eff, r in SPLITS.get(sym, []):
        if d < eff:
            k *= r
    return k


def hr(x, dec=0):
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ================================================================ 1. dohvat
def update(status, quick=False):
    """quick=True: samo cijene (satno osvježavanje tijekom trgovanja); NAV i SKDD ostaju iz zadnjeg punog osvježavanja."""
    today = date.today().isoformat()
    for sym in (("KOEI",) if quick else ("KOEI", "KODT", "KODT2")):
        try:
            rows = S.zse_history(sym, "2023-01-01", today)
            old = read_csv(D / f"zse_{sym}.csv")
            if len(rows) < 0.95 * len(old):
                raise ValueError(f"ZSE vratio {len(rows)} redaka, a bilo ih je {len(old)}")
            write_csv(D / f"zse_{sym}.csv", ["date", "model", "last", "vwap", "trades", "volume", "turnover"],
                      [[r["date"], r["model"], r["last"], r["vwap"], r["trades"], r["volume"], r["turnover"]] for r in rows])
            status[f"ZSE {sym}"] = "ok"
        except Exception as e:
            status[f"ZSE {sym}"] = f"greška: {e}"
    if quick:
        return []
    nav = {(r["datum"], r["fond"]): r["nav_eur"] for r in read_csv(D / "nav.csv")}
    frm = (date.today() - timedelta(days=45)).isoformat()
    down = set()
    for fund in S.FUNDS:
        prov = S.FUNDS[fund][0]
        if prov in down:
            status[f"NAV {fund}"] = "greška: poslužitelj nedostupan (preskočeno)"
            continue
        try:
            got = S.nav_series(fund, frm, today)
            if not got:
                raise ValueError("prazan odgovor")
            for d, v in got.items():
                nav[(d, fund)] = f"{v:.2f}"
            status[f"NAV {fund}"] = f"ok (zadnji {max(got)})"
        except Exception as e:
            status[f"NAV {fund}"] = f"greška: {e}"
            down.add(prov)
    # PBZ CO: NAV koji lokalni zadatak (local/pbz_nav.py) dohvaća s računala u Hrvatskoj
    loc = read_csv(D / "nav_pbz.csv")
    for r in loc:
        nav[(r["datum"], r["fond"])] = r["nav_eur"]
    for fund in ("PBZ_A", "PBZ_B", "PBZ_C"):
        mine = [r["datum"] for r in loc if r["fond"] == fund]
        if mine and not status.get(f"NAV {fund}", "").startswith("ok"):
            status[f"NAV {fund}"] = f"ok (lokalno računalo, zadnji {max(mine)})"
    write_csv(D / "nav.csv", ["datum", "fond", "nav_eur"], [[d, f, v] for (d, f), v in sorted(nav.items())])
    H = read_csv(D / "holdings.csv")
    new = []
    for sym, papir in (("KOEI-R-A", "KOEI"), ("KODT-R-A", "KODT")):
        try:
            snaps, _ = MD.fetch(sym)
            if not snaps or len(snaps[-1]["rows"]) < 5:
                raise ValueError("neočekivan format stranice (nema 5 dioničara)")
            found = {f for r in snaps[-1]["rows"] for k, f in MD_MAP.items() if k in r["puno"]}
            if papir == "KOEI" and not MUST_SEE <= found:
                raise ValueError(f"među prvih 5 nema {', '.join(sorted(MUST_SEE - found))}")
            for snap in snaps:
                for row in snap["rows"]:
                    for key, fond in MD_MAP.items():
                        if key in row["puno"]:
                            cur = holding_at(H, papir, fond, snap["trg"])
                            if cur is None or units(cur, papir) != row["broj"] * sf(papir, snap["datum"]):
                                r = dict(trg=snap["trg"], papir=papir, fond=fond, dionica=str(row["broj"]),
                                         izvor=f"SKDD via MojeDionice (namira {snap['datum']})", tocno="da")
                                H.append(r); new.append(r)
            last = snaps[-1]
            status[f"MojeDionice {papir}"] = f"ok (namira {last['datum']}, T {last['trg']})"
            if papir == "KOEI":
                status["_top10"] = dict(datum=last["datum"], trg=last["trg"], ukupno=last["ukupno_top10"],
                                        top5=sum(r["broj"] for r in last["rows"]))
        except Exception as e:
            status[f"MojeDionice {papir}"] = f"greška: {e}"
    update_mar(status)
    H.sort(key=lambda r: (r["trg"], r["papir"], r["fond"]))
    write_csv(D / "holdings.csv", ["trg", "papir", "fond", "dionica", "izvor", "tocno"],
              [[r["trg"], r["papir"], r["fond"], r["dionica"], r["izvor"], r["tocno"]] for r in H])
    return new


MAR_P = ["objava", "objavljeno", "verzija", "fond", "ocr", "provjera", "redaka", "zbirni_volumen", "zbirna_cijena", "izmjena", "pdf"]
MAR_T = ["objava", "objavljeno", "fond", "trg", "vrsta", "kolicina", "cijena", "provjera"]


def update_mar(status):
    """Nove prijave transakcija rukovoditelja za KOEI → data/mar_pregled.csv (sve obavijesti) i data/mar.csv (transakcije fondova)."""
    P, M = read_csv(D / "mar_pregled.csv"), read_csv(D / "mar.csv")
    # obavijesti pročitane starijom verzijom parsera (E.VERZIJA) čitaju se ponovno
    stare = {r["objava"] for r in P if r.get("verzija") != str(E.VERZIJA)}
    P = [r for r in P if r["objava"] not in stare]; M = [r for r in M if r["objava"] not in stare]
    # mar_rucno.csv: retci obavijesti koje OCR ne može pročitati (prepisani iz PDF-a); i oni moraju odgovarati zbirnim podacima
    rucno = read_csv(D / "mar_rucno.csv")
    stare |= {r["objava"] for r in P if r["objava"] in {x["objava"] for x in rucno} and "ručno" not in r["provjera"]}
    P = [r for r in P if r["objava"] not in stare]; M = [r for r in M if r["objava"] not in stare]
    known = {r["objava"] for r in P}
    od = MAR_OD if not P or stare else max(MAR_OD, (date.fromisoformat(max(r["objavljeno"] for r in P)[:10]) - timedelta(days=45)).isoformat())
    errs = []
    try:
        for ob in reversed(E.lista("KOEI", od)):
            if ob["id"] in known:
                continue
            try:
                r = E.procitaj(S._get(ob["pdf"]))
            except Exception as e:                  # npr. sken bez OCR-a – pokušat će se opet idući put
                errs.append(f"{ob['objavljeno'][:10]}: {e}")
                continue
            f = E.fond(r["osoba"]) or ""
            ruc = [x for x in rucno if x["objava"] == ob["id"]]
            if f and ruc and not r["provjera"].startswith("ok"):     # ručno upisani retci – ista provjera prema zbirnim podacima
                pr, rows = E._provjeri([dict(trg=x["trg"], vrsta=x["vrsta"], kolicina=int(x["kolicina"]), cijena=float(x["cijena"])) for x in ruc],
                                       r["zbirno"], ruc[0]["vrsta"])
                r = dict(r, rows=rows, provjera=pr + " (ručno upisano)" if pr.startswith("ok") else pr)
            zb = r["zbirno"] or ("", "")
            P.append(dict(objava=ob["id"], objavljeno=ob["objavljeno"], verzija=E.VERZIJA, fond=f, ocr="da" if r["ocr"] else "", provjera=r["provjera"],
                          redaka=len(r["rows"]), zbirni_volumen=zb[0], zbirna_cijena=zb[1], izmjena="da" if r["izmjena"] else "", pdf=ob["pdf"]))
            if f:
                M += [dict(objava=ob["id"], objavljeno=ob["objavljeno"], fond=f, provjera=r["provjera"], **x) for x in r["rows"]]
        P.sort(key=lambda r: r["objavljeno"]); M.sort(key=lambda r: (r["trg"], r["objavljeno"]))
        write_csv(D / "mar_pregled.csv", MAR_P, [[r[k] for k in MAR_P] for r in P])
        write_csv(D / "mar.csv", MAR_T, [[r[k] for k in MAR_T] for r in M])
        bad = [r for r in P if r["fond"] and (not r["provjera"].startswith("ok") or r["izmjena"])]
        last = max((r["objavljeno"] for r in P if r["fond"]), default="–")
        status["MAR obavijesti"] = (f"ok (zadnja {last[:10]})" if not (bad or errs) else
                                    f"greška: ručno provjeriti {', '.join([r['objavljeno'][:10] + ' ' + r['provjera'] for r in bad] + errs)}")
    except Exception as e:
        status["MAR obavijesti"] = f"greška: {e}"


def units(r, papir):
    """Pozicija u današnjim jedinicama (nakon eventualne podjele)."""
    ref = r["izvor"].split("namira ")[1][:10] if "namira " in r["izvor"] else r["trg"]
    return int(r["dionica"]) * sf(papir, ref)


def holding_at(H, papir, fond, d):
    best = None
    for r in H:
        if r["papir"] == papir and r["fond"] == fond and r["trg"] <= d and (best is None or r["trg"] >= best["trg"]):
            best = r
    return best


# ================================================================ 2. izračun
def estimate_missing_nav(NAV, days, max_gap=10):
    """Fond kojem izvor kasni (npr. PBZ CO nedostupan s GitHuba): NAV se nastavlja medijanom dnevne promjene
    NAV-a ostalih društava iste kategorije. Najviše max_gap trgovinskih dana; vraća {fond: {datumi procjene}}."""
    est = {}
    for f in list(NAV):
        kat = f.split("_")[1]
        peers = [g for g in NAV if g != f and g.split("_")[1] == kat and g.split("_")[0] != f.split("_")[0]]
        have = sorted(d for d in NAV[f] if d in days)
        if not have:
            continue
        last = have[-1]
        todo = [d for d in days if d > last and sum(1 for g in peers if d in NAV[g]) >= 2][:max_gap]
        prev = last
        for d in todo:
            ch = sorted(NAV[g][d] / NAV[g][prev] for g in peers if d in NAV[g] and prev in NAV[g])
            if len(ch) < 2:
                break
            NAV[f][d] = NAV[f][prev] * ch[len(ch) // 2]
            est.setdefault(f, set()).add(d)
            prev = d
    return est


def mar_after_skdd(Hidx, status):
    """Transakcije iz MAR obavijesti (provjera ok) nakon zadnjeg SKDD stanja fonda postaju nova stanja (tocno="mar").
    Usput: provjera MAR ↔ SKDD – svaka promjena SKDD stanja od početka MAR praćenja mora odgovarati zbroju MAR transakcija."""
    rows = [r for r in read_csv(D / "mar.csv") if r["provjera"].startswith("ok")]
    if not rows:
        return dict(transakcije=[], neslaganja=[])
    start = min(r["trg"] for r in rows)
    sign = lambda r: (-1 if r["vrsta"] == "prodaja" else 1) * int(r["kolicina"]) * sf("KOEI", r["trg"])
    diff, recent = [], []
    for f in sorted({r["fond"] for r in rows}):
        lst = Hidx.setdefault(("KOEI", f), [])
        mine = [r for r in rows if r["fond"] == f]
        skdd = [r for r in lst if r["tocno"] in ("da", "razlika")]
        for a, b in zip(skdd, skdd[1:]):
            if a["trg"] >= start:
                exp = sum(sign(r) for r in mine if a["trg"] < r["trg"] <= b["trg"])
                got = units(b, "KOEI") - units(a, "KOEI")
                if exp != got and b["tocno"] != "razlika":
                    diff.append(dict(fond=f, od=a["trg"], do=b["trg"], skdd=got, mar=exp))
        if not lst:
            continue
        base, t0 = units(lst[-1], "KOEI"), lst[-1]["trg"]
        by = {}
        for r in mine:
            if r["trg"] > t0:
                x = by.setdefault(r["trg"], dict(n=0, kom=0, eur=0.0, obj=r["objavljeno"]))
                x["n"] += sign(r); x["kom"] += int(r["kolicina"]); x["eur"] += int(r["kolicina"]) * float(r["cijena"])
                x["obj"] = max(x["obj"], r["objavljeno"])
        for d in sorted(by):
            base += by[d]["n"]
            lst.append(dict(trg=d, papir="KOEI", fond=f, dionica=str(round(base / sf("KOEI", d))), tocno="mar",
                            izvor=f"MAR obavijest {S.FUNDS[f][0]} na ZSE (objavljena {by[d]['obj'][:10]})",
                            cijena_mar=by[d]["eur"] / by[d]["kom"]))
            recent.append(dict(fond=f, trg=d, dionica=by[d]["n"], cijena=by[d]["eur"] / by[d]["kom"], objavljeno=by[d]["obj"]))
    if diff:
        status["MAR ↔ SKDD"] = "greška: " + "; ".join(f"{x['fond']} {x['od']}–{x['do']}: SKDD {x['skdd']:+}, MAR {x['mar']:+}" for x in diff[-3:])
    else:
        status["MAR ↔ SKDD"] = "ok (slaže se)"
    return dict(transakcije=recent, neslaganja=diff)


def compute(status):
    shares_out = {k: v * sf(k, "0000") for k, v in SHARES_OUT_0.items()}
    zg = zagreb_now(); today = zg.date().isoformat(); before_close = zg.hour * 60 + zg.minute < 16 * 60 + 45
    px, live = {}, None
    for sym in ("KOEI", "KODT", "KODT2"):
        ct, blk = {}, []
        for r in read_csv(D / f"zse_{sym}.csv"):
            if before_close and r["date"] == today:
                if sym == "KOEI" and r["model"] == "CT" and r["last"] not in ("", "None"):
                    live = dict(datum=today, zadnja=float(r["last"]) / sf(sym, today), vwap=float(r["vwap"]) / sf(sym, today),
                                dionica=float(r["volume"]) * sf(sym, today), vrijeme=zg.strftime("%H:%M"))
                continue                                  # dnevni VWAP još nije konačan
            k = sf(sym, r["date"])
            if r["model"] == "BLOCK":
                blk.append(dict(date=r["date"], dionica=float(r["volume"]) * k, cijena=float(r["vwap"] or r["last"] or 0) / k, eur=float(r["turnover"])))
            elif r["model"] == "CT" and r["vwap"] not in ("", "None"):
                ct[r["date"]] = dict(vwap=float(r["vwap"]) / k, last=float(r["last"] or r["vwap"]) / k,
                                     volume=float(r["volume"]) * k, turnover=float(r["turnover"]))
        px[sym] = (ct, blk)
    KO, BLK = px["KOEI"]
    days = sorted(KO)
    NAV = {}
    for r in read_csv(D / "nav.csv"):
        NAV.setdefault(r["fond"], {})[r["datum"]] = float(r["nav_eur"])
    nav_est = estimate_missing_nav(NAV, days)
    Hidx = {}
    for r in read_csv(D / "holdings.csv"):
        Hidx.setdefault((r["papir"], r["fond"]), []).append(r)
    for v in Hidx.values():
        v.sort(key=lambda r: r["trg"])
    mar = mar_after_skdd(Hidx, status)

    def hold(papir, fond, d):
        lst = Hidx.get((papir, fond), [])
        i = bisect_right([r["trg"] for r in lst], d)
        return (units(lst[i - 1], papir), lst[i - 1]) if i else (0, None)

    def last_px(sym, d):
        ct = px[sym][0]; ks = [k for k in ct if k <= d]
        return ct[max(ks)]["vwap"] if ks else 0.0

    def prag(nav, h, c0, lim=LIMIT):
        return lim * (nav - h * c0) / ((1 - lim) * h) if h else None

    def breach_start(dates, ser, lim_pct, tol=0.0):
        s = None
        for d, v in zip(dates, ser):
            if v is None:
                continue
            if v > lim_pct:
                s = s or d
            elif v <= lim_pct - tol:
                s = None
        return s

    # ---- dnevni niz udjela (nezaokruženo za računanje, zaokruženo za JSON)
    hist_from = "2025-11-03"
    dates = [d for d in days if d >= hist_from]
    raw, approx = {}, {}
    for f in TRACK:
        ser, apx = [], []
        for d in dates:
            n = NAV.get(f, {}).get(d)
            h, src = hold("KOEI", f, d)
            ser.append(h * KO[d]["vwap"] / n * 100 if (n and h) else None)
            apx.append(bool(src and src["tocno"] == "izvedeno") or d in nav_est.get(f, ()))
        raw[f], approx[f] = ser, apx
    hist = dict(dates=dates, vwap=[round(KO[d]["vwap"], 2) for d in dates],
                series={f: [None if v is None else round(v, 4) for v in s] for f, s in raw.items()}, approx=approx)

    # ---- stanje po fondu
    funds = []
    for f in TRACK + NO_KOEI:
        drustvo, kat, _ = S.FUNDS[f]
        navs = NAV.get(f, {})
        dn = max((d for d in navs if d in KO), default=None)
        if not dn:
            continue
        nav, vw = navs[dn], KO[dn]["vwap"]
        h, src = hold("KOEI", f, dn)
        lim = LIMIT_C if kat == "C" else LIMIT
        w = h * vw / nav if h else 0.0
        grp = (h * vw + hold("KODT", f, dn)[0] * last_px("KODT", dn) + hold("KODT2", f, dn)[0] * last_px("KODT2", dn)) / nav
        ser = raw.get(f, [])
        since = breach_start(dates, ser, lim * 100) if w > lim else None
        since_early = breach_start(dates, ser, lim * 100, tol=0.02) if w > lim else None
        above_days = sum(1 for d, v in zip(dates, ser) if since and d >= since and v is not None)
        recent_above = [d for d, v in list(zip(dates, ser))[-60:] if v is not None and v > lim * 100] if w <= lim else []
        chg = None
        lst = Hidx.get(("KOEI", f), [])
        for a, b in zip(lst, lst[1:]):
            if units(b, "KOEI") != units(a, "KOEI") and a["tocno"] in OK and b["tocno"] in OK:
                chg = dict(trg=b["trg"], delta=units(b, "KOEI") - units(a, "KOEI"))
        funds.append(dict(
            id=f, drustvo=drustvo, kat=kat, nav=nav, nav_date=dn, nav_procjena=dn in nav_est.get(f, set()), vwap=vw, dionica=h,
            dionica_trg=src["trg"] if src else None, dionica_izvor=src["izvor"] if src else "ne drži KOEI",
            dionica_tocno=bool(src and src["tocno"] in OK), posto_izdanja=h / shares_out["KOEI"],
            vrijednost=h * vw, udio=w, limit=lim, udio_grupa=grp, prag_cijena=prag(nav, h, vw, lim),
            visak5=max(0.0, h - lim * nav / vw) if w > lim else 0.0,
            visak49=max(0.0, h - (lim - 0.001) * nav / vw) if w > lim else 0.0,
            iznad_od=since, iznad_od_rani=since_early, iznad_od_pocetak_povijesti=bool(since and since == dates[0]),
            iznad_dana=above_days, rok_3m=add_months(since, 3) if since else None,
            rok_3m_rani=add_months(since_early, 3) if since_early else None, rok_6m=add_months(since, 6) if since else None,
            nedavno_iznad=recent_above, zadnja_promjena=chg,
            status=("iznad" if w > lim else "blizu" if w > lim - 0.002 else "ispod") if h else "nema"))

    # ---- scenariji cijene (NAV fonda prati vlastitu poziciju KOEI)
    cur = KO[days[-1]]["vwap"]
    step = 50 if cur > 300 else 5
    lo, hi = int(cur * 0.8 // step * step), int(cur * 1.45 // step * step) + step
    grid = sorted(set([round(cur, 2)] + list(range(lo, hi + 1, step))))
    scen = []
    for c in grid:
        row = dict(cijena=c, fondovi={}, ukupno5=0.0, ukupno49=0.0)
        for fx in funds:
            if fx["kat"] != "B" or not fx["dionica"]:
                continue
            nv = fx["nav"] + fx["dionica"] * (c - fx["vwap"])
            n5 = n49 = 0.0
            if fx["dionica"] * c / nv > LIMIT:
                n5 = fx["dionica"] - LIMIT * nv / c; n49 = fx["dionica"] - 0.049 * nv / c
            row["fondovi"][fx["id"]] = round(n5)
            row["ukupno5"] += n5; row["ukupno49"] += n49
        scen.append(row)

    # ---- likvidnost, blokovi, događaji
    def adv(n):
        xs = days[-n:]
        return dict(dana=n, dionica=sum(KO[d]["volume"] for d in xs) / len(xs), eur=sum(KO[d]["turnover"] for d in xs) / len(xs))
    blocks = sorted((b for b in BLK if b["date"] >= (date.today() - timedelta(days=120)).isoformat()), key=lambda b: b["date"], reverse=True)
    events = []
    for f in TRACK:
        lst = Hidx.get(("KOEI", f), [])
        for a, b in zip(lst, lst[1:]):
            dlt = units(b, "KOEI") - units(a, "KOEI")
            if dlt and b["trg"] >= "2025-10-01" and a["tocno"] in OK and b["tocno"] in OK:
                vrsta = "razlika" if b["tocno"] == "razlika" else "abb" if (b["trg"], f) in ABB else ("prodaja" if dlt < 0 else "kupnja")
                events.append(dict(datum=b["trg"], vrsta=vrsta, fond=f, dionica=dlt, stanje=units(b, "KOEI"), izvor=b["izvor"],
                                   cijena=b.get("cijena_mar") or KO.get(b["trg"], {}).get("vwap"), opis=ABB.get((b["trg"], f))))
    for d, t in RESULTS:
        events.append(dict(datum=d, vrsta="rezultati", tekst=f"Končar objavio rezultate {t}"))
    events.sort(key=lambda e: (e["datum"], e["vrsta"] != "rezultati"), reverse=True)

    # ---- promjena među dioničarima 6–10 (gost vidi samo zbroj prvih 10)
    t10 = status.get("_top10")
    last = days[-1]
    B = [fx for fx in funds if fx["kat"] == "B"]
    out = dict(
        generirano=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        koei=dict(datum=last, zadnja=KO[last]["last"], vwap=KO[last]["vwap"], promet=KO[last]["turnover"], dionica=KO[last]["volume"],
                  prethodni_vwap=KO[days[-2]]["vwap"], godinu_ranije=KO[[d for d in days if d <= add_months(last, -12)][-1]]["vwap"]),
        ukupno=dict(visak5=sum(fx["visak5"] for fx in B), visak49=sum(fx["visak49"] for fx in B),
                    eur5=sum(fx["visak5"] * fx["vwap"] for fx in B), eur49=sum(fx["visak49"] * fx["vwap"] for fx in B),
                    fondova_iznad=sum(1 for fx in funds if fx["status"] == "iznad")),
        koei_uzivo=live, fondovi=funds, scenariji=scen, povijest=hist,
        likvidnost=dict(adv20=adv(20), adv60=adv(60), adv250=adv(250),
                        blokovi_ytd=sum(b["dionica"] for b in BLK if b["date"] >= f"{last[:4]}-01-01")),
        blokovi=blocks[:40], dogadaji=events, top10=t10,
        rezultati=dict(svi=RESULTS, zadnji=RESULTS[-1], sljedeci=NEXT_RESULTS,
                       zatvoreno_od=(date.fromisoformat(NEXT_RESULTS[0]) - timedelta(days=30)).isoformat()),
        mar=mar, gs=GS, izvori_status={k: v for k, v in status.items() if not k.startswith("_")},
        shares_out=shares_out["KOEI"], limit=LIMIT,
        moguca_podjela=abs(KO[last]["vwap"] / KO[days[-2]]["vwap"] - 1) > 0.5,
    )
    return out


# ================================================================ 3. obavijesti (šalje ih workflow nakon uspješnog spremanja)
def alerts(new, old, new_holdings):
    if new.get("moguca_podjela"):
        return ["KOEI: cijena se u jednom danu promijenila više od 50 % – moguća podjela dionica; provjeri SPLITS u pipeline/run.py."]
    msgs = []
    if old and old.get("fondovi"):
        ostat = {f["id"]: f["status"] for f in old["fondovi"]}
        for f in new["fondovi"]:
            o = ostat.get(f["id"])
            if o and o != f["status"] and "iznad" in (o, f["status"]):
                msgs.append(f"{f['drustvo']} {f['kat']}: udio {hr(f['udio']*100, 2)} % – {'PREŠAO' if f['status'] == 'iznad' else 'pao ispod'} 5 %")
        az = next((f for f in new["fondovi"] if f["id"] == "AZ_B"), None)
        oaz = old.get("koei", {}).get("vwap")
        if az and az["prag_cijena"] and oaz and new["koei"]["vwap"] >= az["prag_cijena"] * 0.98 > oaz:
            msgs.append(f"KOEI VWAP {hr(new['koei']['vwap'], 2)} € – unutar 2 % od praga AZ B ({hr(az['prag_cijena'], 1)} €)")
        oldb = {(b["date"], round(b["dionica"])) for b in old.get("blokovi", [])}
        for b in new["blokovi"]:
            if (b["date"], round(b["dionica"])) not in oldb and b["dionica"] >= 1000:
                msgs.append(f"Blok KOEI {b['date']}: {hr(b['dionica'])} dionica po {hr(b['cijena'], 2)} €")
        ot, nt = old.get("top10"), new.get("top10")
        if ot and nt and nt["datum"] != ot["datum"] and nt["top5"] == ot["top5"] and nt["ukupno"] != ot["ukupno"]:
            msgs.append(f"Promjena među dioničarima 6–10 (T {nt['trg']}): zbroj prvih 10 {hr(nt['ukupno'] - ot['ukupno'])} dionica – provjeri SKDD")
        bad_new = [k for k, v in new["izvori_status"].items() if not v.startswith("ok")]
        bad_old = [k for k, v in old.get("izvori_status", {}).items() if not str(v).startswith("ok")]
        if bad_new and set(bad_new) != set(bad_old):
            msgs.append("Izvori nisu dohvaćeni: " + ", ".join(bad_new) + " (prikazani su zadnji dostupni podaci)")
    names = {f["id"]: f"{f['drustvo']} {f['kat']}" for f in new["fondovi"]}
    for r in new_holdings:
        if r["papir"] == "KOEI":
            msgs.append(f"{names.get(r['fond'], r['fond'])}: novo stanje {hr(int(r['dionica']))} dionica (trgovanje {r['trg']})")
    if msgs:
        t = new["ukupno"]
        msgs.append(f"Najviše za prodaju do 5 %: {hr(t['visak5'])} dionica ({hr(t['eur5'] / 1e6, 1)} mil. €)")
    return msgs


# ================================================================
if __name__ == "__main__":
    D.mkdir(exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    old = json.load(open(OUT / "latest.json", encoding="utf-8")) if (OUT / "latest.json").exists() else None
    status = {}
    if "--offline" in sys.argv:
        new_h = []
        status = dict((old or {}).get("izvori_status", {})); status["način"] = "ok (offline)"
        if old and old.get("top10"):
            status["_top10"] = old["top10"]
    else:
        quick = "--brzo" in sys.argv
        if quick and old:     # zadrži stanje ostalih izvora iz zadnjeg punog osvježavanja
            status.update({k: v for k, v in old.get("izvori_status", {}).items() if not k.startswith("ZSE KOEI")})
            if old.get("top10"):
                status["_top10"] = old["top10"]
        new_h = update(status, quick=quick)
    data = compute(status)
    json.dump(data, open(OUT / "latest.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    msgs = alerts(data, old, new_h)
    (D / "obavijest.txt").write_text("\n".join(msgs), encoding="utf-8")
    print("\n".join(msgs) or "bez novih obavijesti")
    bad = {k: v for k, v in data["izvori_status"].items() if not v.startswith("ok")}
    print("izvori:", "svi ok" if not bad else bad)
