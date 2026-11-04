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

BASE = "https://eho.zse.hr"
Q = "tx_issuerpublicationmanager_publicnewslisting"
NASLOV = "Prijava transakcija rukovoditelja"
DRUSTVA = [("PBZ CROATIA OSIGURANJE", "PBZ"), ("ERSTE", "ER"), ("RAIFFEISEN", "RF"), (r"\bAZ\b|ALLIANZ", "AZ")]


def lista(ticker="KOEI", od="0000-00-00", max_stranica=30):
    """Prijave transakcija rukovoditelja izdavatelja, najnovije prve: [{id, objavljeno, pdf}] objavljene od `od`."""
    qs = urllib.parse.urlencode({f"{Q}[query]": ticker, f"{Q}[filter]": "ticker"})
    out, seen, chash = [], set(), ""
    for s in range(1, max_stranica + 1):
        url = f"{BASE}/obavijesti-izdavatelja/search{'' if s == 1 else f'/{s}'}?{qs}{chash}"
        h = _get(url).decode("utf-8", "replace")
        if s == 1:
            if "list-group-item" not in h:
                raise ValueError("neočekivan format popisa obavijesti na eho.zse.hr")
            m = re.search(r"cHash=([0-9a-f]+)", h)          # TYPO3 traži cHash za ostale stranice
            chash = f"&cHash={m.group(1)}" if m else ""
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
        if stari or "list-group-item" not in h:
            break
    return out


def _broj(s):
    return float(s.replace(".", "").replace(",", ".").replace(" ", ""))


def _ocr(doc):
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("skenirana obavijest, a tesseract nije instaliran")
    langs = subprocess.run([exe, "--list-langs"], capture_output=True, text=True).stdout.split()
    lang = "hrv+eng" if "hrv" in langs else "eng"
    txt = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(doc):
            png = os.path.join(tmp, f"p{i}.png")
            page.get_pixmap(dpi=300).save(png)
            txt.append(subprocess.run([exe, png, "stdout", "-l", lang, "--psm", "6"], capture_output=True, text=True,
                                      encoding="utf-8").stdout)
    return "\n".join(txt)


def procitaj(pdf_bytes):
    """MAR obrazac → dict(osoba, izmjena, ocr, rows=[{trg, vrsta, kolicina, cijena}], provjera, zbirno)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    t = "\n".join(p.get_text() for p in doc)
    ocr = len(re.sub(r"\s", "", t)) < 200
    if ocr:
        t = _ocr(doc)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    osoba = re.search(r"Ime(?: osobe| i prezime)?:?\s*\|?\s*(.+?)\n\s*\|?\s*2\.", t, re.S)
    osoba = re.sub(r"[\s|]+", " ", osoba.group(1)).strip() if osoba else ""
    izmjena = bool(re.search(r"obavijest\s*/\s*Izmjena\W*\n?\W*Izmjena", t))
    vr = re.search(r"Priroda transakcije\W*(?:-\s*)?([^\n]+)", t)
    vrsta = vr.group(1).lower() if vr else ""
    vrsta = "prodaja" if re.search(r"otpu|prodaj|raspola", vrsta) else "kupnja" if re.search(r"stje|stec|kup", vrsta) else "?"
    tab = t[t.find("Priroda transakcije"):]
    tab = tab[:tab.find("Zbirn")] if "Zbirn" in tab else tab
    rows = [dict(trg=datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d"), vrsta=vrsta, kolicina=int(_broj(n)), cijena=_broj(c))
            for d, c, n in re.findall(r"(\d{1,2}\.\d{1,2}\.\d{4})\.?[\s|]*(\d{1,3}(?:\.\d{3})*,\d{2,4})\s*(?:EUR|€)?[\s|]*(\d{1,3}(?:\.\d{3})*)(?![\d,])", tab)]
    zv = re.search(r"Zbirni volumen:?\s*(\d{1,3}(?:\.\d{3})*)", t)
    zc = re.search(r"Cijena[^:\n]*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2,4})\s*(?:EUR|€)", t[zv.end():] if zv else "")
    zbirno = (int(_broj(zv.group(1))), _broj(zc.group(1))) if zv and zc else None
    if not rows:
        provjera = "nema redaka"
    elif "HRKOEIRA0009" not in t.replace(" ", "") and "KOEI" not in t:
        provjera = "nije KOEI"
    elif vrsta == "?":
        provjera = "nepoznata vrsta transakcije"
    elif not zbirno:
        provjera = "nema zbirnih podataka"
    else:
        n = sum(r["kolicina"] for r in rows)
        vw = sum(r["kolicina"] * r["cijena"] for r in rows) / n
        provjera = "ok" if n == zbirno[0] and abs(vw - zbirno[1]) <= 0.011 else f"zbroj {n} / {vw:.2f} ≠ zbirno {zbirno[0]} / {zbirno[1]:.2f}"
    return dict(osoba=osoba, izmjena=izmjena, ocr=ocr, rows=rows, provjera=provjera, zbirno=zbirno)


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
