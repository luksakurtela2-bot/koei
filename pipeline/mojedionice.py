"""MojeDionice.com – promjene top dioničara (gost: prvih 5). Izvor podataka je SKDD; stanje po namiri (T+2), uz datum trgovanja T."""
import re, html, time, urllib.request
from datetime import datetime

BASE = "https://www.mojedionice.com/trg/IzvDionicariPromjene.aspx?sifSim={sym}"
UA = {"User-Agent": "Mozilla/5.0 (KOEI-monitor; osobna uporaba)"}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")


def _num(s):
    return float(s.replace(".", "").replace(",", ".").replace("%", "").strip())


def _iso(d):
    for f in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(d, f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(d)


def parse(page):
    """→ list of snapshots {datum (namira), trg (T), cijena, rows:[{ime, puno, broj, posto}], ukupno}"""
    out = []
    heads = list(re.finditer(r'<span title="[^"]*">(\d\d\.\d\d\.\d{4})</span>\s*(?:<a [^>]*>.*?</a>\s*)?</th>\s*<th[^>]*>T:\s*(\d\d\.\d\d\.\d\d)(?:&nbsp;)*\s*Pros\. cijena:\s*([\d.,]+)', page))
    for i, h in enumerate(heads):
        seg = page[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(page)]
        rows = []
        for m in re.finditer(r"showttip\('([^']*)'.*?>([^<]*)</span></a></td>\s*<td[^>]*>([\d.]+)</td>\s*<td[^>]*>([\d,]+)%</td>", seg, re.S):
            puno = html.unescape(m.group(1).split("<br/>")[0])
            rows.append(dict(puno=puno, ime=html.unescape(m.group(2)).strip(), broj=int(_num(m.group(3))), posto=_num(m.group(4))))
        tot = re.search(r"<th>UKUPNO</th>\s*<th>([\d.]+)</th>", seg)
        out.append(dict(datum=_iso(h.group(1)), trg=_iso(h.group(2)), cijena=_num(h.group(3)), rows=rows,
                        ukupno_top10=int(_num(tot.group(1))) if tot else None))
    prev = re.search(r'maxDat=(\d\d\.\d\d\.\d{4})" title="Prethodni datum"', page)
    return out, (prev.group(1) if prev else None)


def fetch(sym, max_dat=None):
    url = BASE.format(sym=sym) + (f"&maxDat={max_dat}" if max_dat else "")
    return parse(_get(url))


def crawl(sym, stop_iso, pause=1.5, max_pages=200):
    """Unatrag od najnovijeg do stop_iso. Vraća sve snimke (svaki datum promjene jednom)."""
    snaps, nxt, n = {}, None, 0
    while n < max_pages:
        page_snaps, prev = fetch(sym, nxt)
        for s in page_snaps:
            snaps[s["datum"]] = s
        n += 1
        if not prev or not page_snaps or prev == nxt or min(s["datum"] for s in page_snaps) <= stop_iso:
            break
        nxt = prev
        time.sleep(pause)
    return [snaps[k] for k in sorted(snaps)]


if __name__ == "__main__":
    import json, sys
    s, prev = fetch("KOEI-R-A")
    print(json.dumps(s, ensure_ascii=False, indent=1)[:1500], prev)
