"""Dohvat javnih podataka: ZSE (cijene/VWAP), dnevni NAV četiriju mirovinskih društava."""
import csv, io, json, re, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta

UA = {"User-Agent": "Mozilla/5.0 (KOEI-monitor; osobna uporaba)"}
ZSE_TOKEN = "Bvt9fe2peQ7pwpyYqODM"          # javni web token zse.hr
ISIN = {"KOEI": "HRKOEIRA0009", "KODT": "HRKODTRA0007", "KODT2": "HRKODTPA0009"}

# fond → parametri izvora (provjereno 3.11.2026.; NAV = HANFA na krajevima mjeseci)
FUNDS = {
    "AZ_A": ("AZ", "A", {"az": 12}), "AZ_B": ("AZ", "B", {"az": 1}), "AZ_C": ("AZ", "C", {"az": 13}),
    "ER_A": ("Erste Plavi", "A", {"erste": 1015}), "ER_B": ("Erste Plavi", "B", {"erste": 1005}), "ER_C": ("Erste Plavi", "C", {"erste": 1025}),
    "PBZ_A": ("PBZ CO", "A", {"pbz": 3}), "PBZ_B": ("PBZ CO", "B", {"pbz": 1}), "PBZ_C": ("PBZ CO", "C", {"pbz": 4}),
    "RF_A": ("Raiffeisen", "A", {"rf": "A"}), "RF_B": ("Raiffeisen", "B", {"rf": "B"}), "RF_C": ("Raiffeisen", "C", {"rf": "C"}),
}


def _get(url, data=None, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def _dmy(s):
    return datetime.strptime(s.strip("."), "%d.%m.%Y").strftime("%Y-%m-%d")


# ---------------------------------------------------------------- ZSE
def zse_history(sym, frm="2023-01-01", to=None):
    to = to or date.today().isoformat()
    url = f"https://rest.zse.hr/web/{ZSE_TOKEN}/security-history/XZAG/{ISIN[sym]}/{frm}/{to}/json"
    rows = json.loads(_get(url))["history"]
    return sorted(({"date": r["date"], "model": r["trading_model_id"], "last": float(r["last_price"]) if r["last_price"] else None,
                    "vwap": float(r["vwap_price"]) if r["vwap_price"] else None, "trades": r["num_trades"],
                    "volume": float(r["volume"] or 0), "turnover": float(r["turnover"] or 0)} for r in rows),
                  key=lambda r: (r["date"], r["model"]))


# ---------------------------------------------------------------- NAV
_AZ_TOKEN = None
def _az_token():
    global _AZ_TOKEN
    if not _AZ_TOKEN:
        h = _get("https://www.azfond.hr/obvezni-mirovinski-fond/kategorija-b/kretanje-vrijednosti-obracunske-jedinice/").decode("utf-8", "replace")
        _AZ_TOKEN = re.search(r"token='\"([0-9a-f]+)\"'", h).group(1)
    return _AZ_TOKEN


def nav_series(fund, frm, to):
    """→ {iso_datum: nav_eur}"""
    src = FUNDS[fund][2]
    if "az" in src:
        body = urllib.parse.urlencode({"token": _az_token(), "fondID": src["az"], "dateFrom": _d(frm), "dateTo": _d(to)}).encode()
        d = json.loads(_get("https://www.azfond.hr/wp-json/wp/ea/get_chart_data", body, {"Content-Type": "application/x-www-form-urlencoded"}))
        return {_dmy(x): float(n) for x, n in zip(d["Datum"], d["NAV"])}
    if "erste" in src:
        txt = _get(f"https://www.ersteplavi.hr/wp-admin/admin-ajax.php?action=export_csv&portfoliocode={src['erste']}").decode("utf-8", "replace")
        out = {}
        for line in txt.splitlines():
            p = line.strip().split(";")
            if len(p) == 3 and re.match(r"\d{4}-\d\d-\d\d", p[0]) and frm <= p[0] <= to:
                out[p[0]] = float(p[2].replace(",", "."))
        return out
    if "pbz" in src:
        d = json.loads(_get(f"https://www.pbzco-fond.hr/api/wsdl/get-nav?fond_id={src['pbz']}&dateFrom={frm}&dateTo={to}"))
        return {x["datum"][:10]: float(x["NAV"]) for x in d["data"]["NAVrez"]}
    if "rf" in src:
        d = json.loads(_get(f"https://www.rmf.hr/Ajax.aspx?action=nav&sifra={src['rf']}&tmpDateFrom={_d(frm)}&tmpDateTo={_d(to)}"))
        return {_dmy(x["Datum"]): float(x["ValueEur"]) for x in d["VrijednostUdjelaVM"]}
    raise KeyError(fund)


def _d(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"
