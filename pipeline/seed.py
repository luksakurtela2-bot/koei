"""Jednokratno: početna povijest iz analize 3.11.2026. (../../notes, ../../out) → data/nav.csv, data/holdings.csv."""
import csv, json, sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
K = APP.parent                                  # KOEI mirovinci
D = APP / "data"; D.mkdir(parents=True, exist_ok=True)
FID = {("AZ", "A"): "AZ_A", ("AZ", "B"): "AZ_B", ("AZ", "C"): "AZ_C", ("Erste Plavi", "A"): "ER_A", ("Erste Plavi", "B"): "ER_B",
       ("Erste Plavi", "C"): "ER_C", ("PBZ CO", "A"): "PBZ_A", ("PBZ CO", "B"): "PBZ_B", ("PBZ CO", "C"): "PBZ_C",
       ("Raiffeisen", "A"): "RF_A", ("Raiffeisen", "B"): "RF_B", ("Raiffeisen", "C"): "RF_C"}

# ---------------- NAV (dnevni, API društava; = HANFA na krajevima mjeseci)
nav = {}
for fn in ("notes/05b_nav_dnevno_2025_2026.csv", "notes/05_voj_dnevno.csv"):
    for r in csv.DictReader(open(K / fn, encoding="utf-8-sig")):
        if r["neto_imovina_eur_ako_postoji"]:
            nav[(r["datum"], FID[(r["drustvo"], r["kategorija"])])] = float(r["neto_imovina_eur_ako_postoji"])
with open(D / "nav.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["datum", "fond", "nav_eur"])
    for (d, fd), v in sorted(nav.items()):
        w.writerow([d, fd, f"{v:.2f}"])

# ---------------- pozicije KOEI (trg = datum trgovanja od kojeg vrijedi stanje)
H = []
def add(trg, fond, broj, izvor, tocno=True, papir="KOEI"):
    H.append([trg, papir, fond, int(broj), izvor, tocno if isinstance(tocno, str) else ("da" if tocno else "izvedeno")])

# PBZ CO B: dnevno iz MAR obavijesti PBZ CO (član NO Končara), od 3.11.2025.
M = json.load(open(K / "out/model.json", encoding="utf-8"))
prev = None
UNEXPL = {"2026-05-15": 1988}     # razlika obavijesti prema mjesečnom portfelju fonda (30.4. → 31.5.2026.)
for r in M["pbz_dnevno"]:
    if r["dionica"] != prev:
        if r["datum"] in UNEXPL:
            add(r["datum"], "PBZ_B", r["dionica"] + UNEXPL[r["datum"]], "PBZ CO obavijesti o transakcijama (MAR)")
            add(r["datum"], "PBZ_B", r["dionica"], "razlika prema mjesečnom portfelju fonda (neobjašnjena)", tocno="razlika")
        else:
            add(r["datum"], "PBZ_B", r["dionica"], "PBZ CO obavijesti o transakcijama (MAR)")
        prev = r["dionica"]
# Erste Plavi B: mjesečni portfelj fonda (izvedeno iz % NAV-a ±0,2 %) do 9/2026; od 10/2026 MojeDionice/SKDD
for r in csv.DictReader(open(K / "notes/03_fondovi_AZ_Erste.csv", encoding="utf-8-sig")):
    if "KOEI" in r["izdavatelj"] and r["kategorija"] == "B" and r["drustvo"].startswith("Erste") and "2025-01" <= r["datum_stanja"] <= "2026-09-30":
        exact = r["izvor"].startswith("[IZVORNO]")
        # izvedeno stanje s kraja mjeseca vrijedi od početka tog mjeseca (fond samo prodaje → donja granica udjela)
        add(r["datum_stanja"] if exact else r["datum_stanja"][:8] + "01", "ER_B", r["broj_dionica"], "Erste Plavi – portfelj fonda", tocno=exact)
# AZ B: nepromijenjeno od 2025. (izvješća 30.6.2025., 31.12.2025., 30.6.2026.; SKDD 3.11.2026.)
add("2025-04-04", "AZ_B", 398065, "AZ OMF izvješća + SKDD")
# Raiffeisen B: nepromijenjeno od 2022. (izvješća; SKDD 3.11.2026.)
add("2022-12-31", "RF_B", 47636, "nepromijenjeno od 2022. (izvješća fonda; SKDD 3.11.2026.)")
# A fondovi
add("2025-12-08", "PBZ_A", 29084, "PBZ CO obavijesti + SKDD 3.11.2026.")
add("2026-06-30", "ER_A", 11399, "Erste Plavi izvješće 30.6.2026.")
add("2026-06-30", "RF_A", 8326, "Raiffeisen izvješće 30.6.2026.")
add("2026-06-30", "AZ_A", 2911, "AZ OMF izvješće 30.6.2026.")
# KODT / KODT2 (grupni limit)
add("2025-06-30", "AZ_B", 20122, "AZ OMF izvješća 30.6.2025.–30.6.2026.; SKDD 3.11.2026.", papir="KODT")
add("2025-06-30", "AZ_B", 3214, "AZ OMF izvješća 30.6.2025.–30.6.2026.", papir="KODT2")
add("2026-06-30", "PBZ_A", 4228, "SKDD 3.11.2026.", papir="KODT")

# MojeDionice (SKDD, T+2) – listopad 2026.
sys.path.insert(0, str(APP / "pipeline"))
import mojedionice as md
from run import MD_MAP
for snap in json.load(open(APP / "data_seed/md_KOEI.json", encoding="utf-8")):
    for row in snap["rows"]:
        for key, fond in MD_MAP.items():
            if key in row["puno"]:
                add(snap["trg"], fond, row["broj"], f"SKDD via MojeDionice (namira {snap['datum']})")
H.sort(key=lambda r: (r[0], r[1], r[2]))
with open(D / "holdings.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["trg", "papir", "fond", "dionica", "izvor", "tocno"]); w.writerows(H)
print(len(nav), "NAV redaka;", len(H), "pozicija")
