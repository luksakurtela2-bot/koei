"""MAR obavijesti o transakcijama rukovoditelja (čl. 19. MAR-a) za KOEI s eho.zse.hr.

PBZ CO prijavljuje svaku transakciju svojih fondova jer je Rosa Marić (predsjednica Uprave PBZ CO) članica NO Končara.
Obavijest stiže 1–3 radna dana nakon transakcije – prije nego SKDD (T+2) pokaže promjenu na MojeDionicama.
Dio obavijesti su skenovi: tada OCR (tesseract). Svaka se obavijest provjerava prema „Zbirnim informacijama”
(zbirni volumen = zbroj redaka, prosječna cijena = ponderirani prosjek); što se ne slaže, ne ulazi u izračun.

    python pipeline/eho.py --od 2025-11-01   # ispis svih obavijesti od datuma (provjera parsera)
"""
import os, re, shutil, subprocess, sys, tempfile, urllib.parse
from datetime import datetime
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sources import _get

VERZIJA = 4                 # povećati kad se promijeni čitanje obavijesti → sve se ponovno pročitaju
BASE = "https://eho.zse.hr"
Q = "tx_issuerpublicationmanager_publicnewslisting"
NASLOV = "Prijava transakcija rukovoditelja"
DRUSTVA = [("PBZ CROATIA OSIGURANJE", "PBZ"), ("ERSTE", "ER"), ("RAIFFEISEN", "RF"), (r"\bAZ\b|ALLIANZ", "AZ")]


def lista(ticker="KOEI", od="0000-00-00", max_stranica=30):
    """Prijave transakcija rukovoditelja izdavatelja, najnovije prve: [{id, objavljeno, pdf}] objavljene od `od`."""
    qs = urllib.parse.urlencode({f"{Q}[query]": ticker, f"{Q}[filter]": "ticker"})
    out, seen, nxt = [], set(), None
    for s in range(1, max_stranica + 1):
        url = f"{BASE}/obavijesti-izdavatelja/search?{qs}" if s == 1 else nxt.replace("/search/2?", f"/search/{s}?")
        h = _get(url).decode("utf-8", "replace")
        if s == 1:
            if "list-group-item" not in h:
                raise ValueError("neočekivan format popisa obavijesti na eho.zse.hr")
            # ostale stranice: točno kao poveznica na 2. stranicu (TYPO3 cHash ovisi o redoslijedu parametara)
            m = re.search(r'href="(/obavijesti-izdavatelja/search/2\?[^"]+)"', h)
            nxt = BASE + m.group(1).replace("&amp;", "&") if m else None
        stari = False
        for blk in h.split('class="list-group-item')[1:]:
            m = re.search(r"(\d\d\.\d\d\.\d{4})\.\s+(\d\d:\d\d)\s*<span[^>]*>&ndash;\s*([^<]*)</span>", blk)
            v = re.search(r"/obavijesti-izdavatelja/view/(\d+)", blk)
            p = re.search(r'href="(/fileadmin/issuers/[^"]+\.pdf)"', blk)
            if not (m and v):
                continue
            kad = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d.%m.%Y %H:%M").strftime("%Y-%m-%d %H:%M")
            if kad < od:
                stari = True
                continue
            if m.group(3).strip() == NASLOV and v.group(1) not in seen and p:
                seen.add(v.group(1))
                out.append(dict(id=v.group(1), objavljeno=kad, pdf=BASE + p.group(1)))
        if stari or not nxt or "list-group-item" not in h:
            break
    return out


def _datum(d):
    try:
        return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:                                     # OCR pogreška (npr. 80.12.2025.)
        return None


def _broj(s):
    return float(s.replace(".", "").replace(",", ".").replace(" ", ""))


OCR_POKUSAJI = [("6", 300, True), ("6", 300, False), ("4", 300, True), ("6", 400, True), ("11", 300, True)]  # (psm, dpi, bez crta)


def _bez_crta(pix):
    """Ukloni crte tablice (tamni nizovi dulji od ~1 cm) – tesseract u uokvirenim ćelijama preskače kratke brojeve."""
    import numpy as np
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    dark = a < 150
    lim = pix.width // 20                                   # ~1 cm pri 300 dpi
    for m, view in ((dark, a), (dark.T, a.T)):              # vodoravno pa okomito
        p = np.pad(m, ((0, 0), (1, 1))).astype(np.int8)
        d = np.diff(p, axis=1)
        for r, c0 in zip(*np.nonzero(d == 1)):
            c1 = c0 + np.argmax(d[r, c0:] == -1)
            if c1 - c0 > lim:
                view[max(r - 1, 0):r + 2, c0:c1] = 255
    return pymupdf.Pixmap(pymupdf.csGRAY, pix.width, pix.height, a.tobytes(), False)


def _ocr(doc, psm="6", dpi=300, clean=True, tsv=False):
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("skenirana obavijest, a tesseract nije instaliran")
    langs = subprocess.run([exe, "--list-langs"], capture_output=True, text=True).stdout.split()
    lang = "hrv+eng" if "hrv" in langs else "eng"
    txt = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(doc):
            png = os.path.join(tmp, f"p{i}.png")
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            (_bez_crta(pix) if clean else pix).save(png)
            txt.append(subprocess.run([exe, png, "stdout", "-l", lang, "--psm", psm] + (["tsv"] if tsv else []),
                                      capture_output=True, text=True, encoding="utf-8").stdout)
    return txt if tsv else "\n".join(txt)


RX_DAT, RX_CIJ, RX_VOL = r"\d{1,2}\.\d{1,2}\.\d{4}\.?", r"\d{1,3}(?:\.\d{3})*,\d{2,4}", r"\d{1,3}(?:\.\d{3})*"


def _redci_tsv(doc):
    """Retci tablice iz položaja riječi (tesseract TSV, rijetki tekst): datum → cijena desno → volumen desno, u istoj visini."""
    rows = []
    for page in _ocr(doc, "11", 300, True, tsv=True):
        W = []
        for ln in page.splitlines()[1:]:
            c = ln.split("\t")
            if len(c) == 12 and c[11].strip():
                W.append(dict(x=int(c[6]), y=int(c[7]) + int(c[9]) / 2, h=int(c[9]), t=c[11].strip().strip("|")))
        for d in (w for w in W if re.fullmatch(RX_DAT, w["t"]) and _datum(w["t"].rstrip("."))):
            row = sorted((w for w in W if w["x"] > d["x"] and abs(w["y"] - d["y"]) < 0.8 * d["h"]), key=lambda w: w["x"])
            cij = next((w for w in row if re.fullmatch(RX_CIJ, w["t"])), None)
            vol = next((w for w in row if cij and w["x"] > cij["x"] and re.fullmatch(RX_VOL, w["t"])), None)
            if cij:
                rows.append(dict(trg=_datum(d["t"].rstrip(".")), kolicina=int(_broj(vol["t"])) if vol else None, cijena=_broj(cij["t"])))
    return rows


def procitaj(pdf_bytes):
    """MAR obrazac → dict(osoba, izmjena, ocr, rows=[{trg, vrsta, kolicina, cijena}], provjera, zbirno).
    Sken: OCR redom po OCR_POKUSAJI dok provjera prema zbirnim podacima ne prođe. Ako nijedan prolaz sam ne prođe,
    volumeni koje jedan prolaz ne pročita uzimaju se iz drugih (isti datum i cijena, uključivo položaje riječi) –
    spojeni rezultat opet mora proći istu provjeru."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    t = "\n".join(p.get_text() for p in doc)
    if len(re.sub(r"\s", "", t)) >= 200:
        return _parse(t, ocr=False)
    tries = []
    for psm, dpi, clean in OCR_POKUSAJI:
        r = _parse(_ocr(doc, psm, dpi, clean), ocr=True)
        if r["provjera"].startswith("ok") or not fond((tries[0] if tries else r)["osoba"]):
            return r
        tries.append(r)
        if len(tries) == 1:
            tries.append(dict(r, rows=_redci_tsv(doc), vrsta_doc="?"))
        vrsta = next((x["vrsta_doc"] for x in tries if x["vrsta_doc"] != "?"), "?")
        zbirno = next((x["zbirno"] for x in tries if x["zbirno"]), None)
        vol = {}
        for x in tries:
            for row in x["rows"]:
                if row["kolicina"]:
                    vol.setdefault((row["trg"], row["cijena"]), set()).add(row["kolicina"])
        for base in sorted(tries, key=lambda x: -len(x["rows"])):
            rows = []
            for row in base["rows"]:
                v = vol.get((row["trg"], row["cijena"]), set())
                rows.append(dict(row, vrsta=vrsta, kolicina=row["kolicina"] or (next(iter(v)) if len(v) == 1 else None)))
            pr, rows = _provjeri(rows, zbirno, vrsta)
            if pr.startswith("ok"):
                return dict(tries[0], rows=rows, zbirno=zbirno, provjera=pr + " (spojeno iz više OCR prolaza)")
    return tries[0]


def _provjeri(rows, zbirno, vrsta, koei=True):
    """Retci moraju dati zbirni volumen i prosječnu cijenu iz iste obavijesti → (provjera, retci)."""
    rows = [dict(r) for r in rows]
    miss = [r for r in rows if r["kolicina"] is None]
    dopuna = False
    if zbirno and len(miss) == 1:                  # jedan nepročitan volumen = zbirni − ostali; potvrđuje ga prosječna cijena
        miss[0]["kolicina"] = zbirno[0] - sum(r["kolicina"] for r in rows if r is not miss[0])
        dopuna = miss[0]["kolicina"] > 0
    if not rows:
        return "nema redaka", rows
    if any(r["trg"] is None for r in rows):
        return "nepročitan datum", rows
    if any(r["kolicina"] is None or r["kolicina"] <= 0 for r in rows):
        return "nepročitan volumen", rows
    if not koei:
        return "nije KOEI", rows
    if vrsta == "?":
        return "nepoznata vrsta transakcije", rows
    if not zbirno:
        return "nema zbirnih podataka", rows
    n = sum(r["kolicina"] for r in rows)
    vw = sum(r["kolicina"] * r["cijena"] for r in rows) / n
    if n == zbirno[0] and abs(vw - zbirno[1]) <= 0.011:
        return ("ok (jedan volumen iz zbirnog)" if dopuna else "ok"), rows
    return f"zbroj {n} / {vw:.2f} ≠ zbirno {zbirno[0]} / {zbirno[1]:.2f}", rows


def _parse(t, ocr):
    t = re.sub(r"[ \t ]+", " ", t)
    sek1 = re.search(r"Podaci o osobi[^\n]*\n(.+?)(?:\n[^\n]*)?Razlog obavje", t, re.S)       # odjeljak 1. obrasca
    ime = re.search(r"Ime(?: osobe| i prezime)?:?\s*\|?\s*(.+?)\n\s*\|?\s*2\.", t, re.S)
    osoba = next((re.sub(r"[\s|]+", " ", m.group(1)).strip() for m in (sek1, ime) if m and fond(m.group(1))),
                 re.sub(r"[\s|]+", " ", (ime or sek1).group(1)).strip() if (ime or sek1) else "")
    izmjena = bool(re.search(r"obavijest\s*/\s*Izmjena\W*\n?\W*Izmjena", t))
    vr = re.search(r"Priroda transakcije\W*(?:-\s*)?([^\n]+)", t)
    vrsta = vr.group(1).lower() if vr else ""
    vrsta = "prodaja" if re.search(r"otpu|prodaj|raspola", vrsta) else "kupnja" if re.search(r"stje|stec|kup", vrsta) else "?"
    if vrsta == "?":                               # OCR nije pročitao redak – vrsta iz predmeta dopisa ili teksta obavijesti
        pr = re.search(r"Predmet:(.{0,120})", t, re.S)
        low = (pr.group(1) if pr else t).lower()
        ima_p, ima_k = bool(re.search(r"otpu[sš]t|otpustio|prodaj", low)), bool(re.search(r"stjecanj|stekao|kupnj", low))
        vrsta = "prodaja" if ima_p and not ima_k else "kupnja" if ima_k and not ima_p else "?"
    tab = t[t.find("Priroda transakcije"):]
    tab = tab[:tab.find("Zbirn")] if "Zbirn" in tab else tab
    sp = r"[ |]*" if ocr else r"[\s|]*"           # OCR: redak tablice je jedan redak teksta; volumen može nedostajati
    rows = [dict(trg=_datum(d.rstrip(".")), vrsta=vrsta, kolicina=int(_broj(n)) if n else None, cijena=_broj(c))
            for d, c, n in re.findall(r"(" + RX_DAT + r")[\s|]*(" + RX_CIJ + r")\s*(?:EUR|€)?" + sp + r"(" + RX_VOL + r")?(?![\d,])", tab)]
    zv = re.search(r"Zbirni\s*volumen:?\s*(" + RX_VOL + r")", t)
    zc = re.search(r"Cijena[^:\n]*:?\s*(" + RX_CIJ + r")\s*(?:EUR|€)", t[zv.end():] if zv else "")
    zbirno = (int(_broj(zv.group(1))), _broj(zc.group(1))) if zv and zc else None
    koei = "HRKOEIRA0009" in t.replace(" ", "") or "KOEI" in t
    provjera, rows = _provjeri(rows, zbirno, vrsta, koei)
    return dict(osoba=osoba, izmjena=izmjena, ocr=ocr, rows=rows, provjera=provjera, zbirno=zbirno, vrsta_doc=vrsta)


def fond(osoba):
    o = osoba.upper().replace("Č", "C").replace("Ć", "C").replace("Š", "S").replace("Ž", "Z")
    if "MIROVINSK" not in o:
        return None
    dr = next((k for rx, k in DRUSTVA if re.search(rx, o)), None)
    kat = re.search(r"KATEGORIJ[AEI]\W*([ABC])\b", o)
    return f"{dr}_{kat.group(1)}" if dr and kat else None


if __name__ == "__main__":
    od = sys.argv[sys.argv.index("--od") + 1] if "--od" in sys.argv else "2026-10-01"
    for ob in reversed(lista("KOEI", od)):
        r = procitaj(_get(ob["pdf"]))
        f = fond(r["osoba"])
        print(ob["objavljeno"], ob["id"], f or "(osoba)", "OCR" if r["ocr"] else "tekst", r["provjera"], r["zbirno"], "IZMJENA" if r["izmjena"] else "")
        if f:
            for x in r["rows"]:
                print("   ", x["trg"], x["vrsta"], x["kolicina"], x["cijena"])
