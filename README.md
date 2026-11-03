# KOEI × obvezni mirovinski fondovi

Dnevno praćenje udjela Končara (KOEI) u neto imovini obveznih mirovinskih fondova prema limitu od 5 % (ZOMF čl. 127. st. 2.): tko je iznad limita, koliko mora prodati, tko je prodavao.

- **Stranica**: `docs/` (GitHub Pages, PWA – na mobitelu „Dodaj na početni zaslon”).
- **Podaci**: `pipeline/run.py` radnim danom oko 9:15 i 18:20 zimi, odnosno 10:15 i 19:20 ljeti (GitHub Actions) dohvaća ZSE, dnevni NAV četiriju društava i promjene dioničara (SKDD preko MojeDionice), računa i sprema `docs/data/latest.json` (radni CSV-ovi u `data/`).
- **Obavijesti**: ntfy.sh – pretplata u aplikaciji ntfy na temu iz tajne `NTFY_TOPIC`.
- **Ručno pokretanje**: Actions → „Osvježi podatke” → Run workflow. Lokalno: `python pipeline/run.py` (samo standardna biblioteka).

Metodologija je opisana na samoj stranici (odjeljak „Kako se računa”). Podaci kasne 1–2 radna dana (namira T+2, NAV dan poslije). Osobni alat, ne savjet za ulaganje.
