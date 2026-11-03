"""Lokalni zadatak (Windows Task Scheduler): PBZ CO NAV → data/nav_pbz.csv → GitHub.

PBZ CO poslužitelj odgovara samo hrvatskim adresama, pa ga GitHub Actions ne može dohvatiti.
Pokreće se iz zasebnog klona repozitorija (C:\\Users\\lkurtela\\koei-pbz); dira samo data/nav_pbz.csv.
"""
import csv, json, subprocess, sys, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "nav_pbz.csv"
LOG = REPO.parent / "koei-pbz.log"
FUNDS = {"PBZ_A": 3, "PBZ_B": 1, "PBZ_C": 4}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {msg}\n")


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=120)


def main():
    r = git("pull", "--rebase", "-X", "theirs", "origin", "main")
    if r.returncode:
        log(f"pull: {r.stderr.strip()[:300]}")
    rows = {}
    if OUT.exists():
        for x in csv.DictReader(open(OUT, encoding="utf-8")):
            rows[(x["datum"], x["fond"])] = x["nav_eur"]
    frm, to = (date.today() - timedelta(days=14)).isoformat(), date.today().isoformat()
    for fond, fid in FUNDS.items():
        url = f"https://www.pbzco-fond.hr/api/wsdl/get-nav?fond_id={fid}&dateFrom={frm}&dateTo={to}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KOEI-monitor; osobna uporaba)"})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        for x in d["data"]["NAVrez"]:
            rows[(x["datum"][:10], fond)] = f"{float(x['NAV']):.2f}"
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["datum", "fond", "nav_eur"])
        w.writerows([d, fd, v] for (d, fd), v in sorted(rows.items()))
    git("add", "data/nav_pbz.csv")
    if git("diff", "--cached", "--quiet").returncode == 0:
        log("bez promjene"); return
    git("commit", "-m", f"PBZ CO NAV (lokalno) {date.today().isoformat()}")
    for _ in range(3):
        if git("push", "origin", "main").returncode == 0:
            log(f"poslano, zadnji {max(d for d, _ in rows)}"); return
        git("pull", "--rebase", "-X", "theirs", "origin", "main")
    log("push nije uspio")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"greška: {e}"); sys.exit(1)
