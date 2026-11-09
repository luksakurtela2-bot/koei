"""Lokalni zadatak (Windows Task Scheduler, radnim danom svaki sat 9:35–19:35): rezerva za GitHubova zakazana pokretanja.

GitHub zakazana pokretanja (cron) zna kasniti satima ili ih preskočiti (5. i 9. 11. 2026. jutro bez ijednog).
Ako zadnje osvježavanje podataka ("Podaci …" commit) nije novije od 90 minuta, upiše vrijeme u local/okidac.txt
i gurne ga – to pokreće workflow "Osvježi podatke" (push na local/okidac.txt) odmah.
Radi iz istog zasebnog klona kao pbz_nav.py (C:\\Users\\lkurtela\\koei-pbz); dira samo local/okidac.txt.
"""
import subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG = REPO.parent / "koei-pbz.log"
MAX_MIN = 90


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} okidač: {msg}\n")


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=120)


def main():
    if datetime.now().weekday() > 4:
        return
    r = git("pull", "--rebase", "-X", "theirs", "origin", "main")
    if r.returncode:
        log(f"pull: {r.stderr.strip()[:300]}"); return
    t = git("log", "-1", "--grep=^Podaci ", "--format=%ct", "origin/main").stdout.strip()
    age = (datetime.now(timezone.utc).timestamp() - int(t)) / 60 if t else 1e9
    if age <= MAX_MIN:
        return
    f = REPO / "local" / "okidac.txt"
    f.write_text(f"{datetime.now():%Y-%m-%d %H:%M} – zadnje osvježavanje prije {age:.0f} min\n", encoding="utf-8")
    git("add", "local/okidac.txt")
    git("commit", "-m", f"Okidač osvježavanja (zadnje prije {age:.0f} min)")
    for _ in range(3):
        if git("push", "origin", "main").returncode == 0:
            log(f"pokrenuto (zadnje osvježavanje prije {age:.0f} min)"); return
        git("pull", "--rebase", "-X", "theirs", "origin", "main")
    log("push nije uspio")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"greška: {e}"); sys.exit(1)
