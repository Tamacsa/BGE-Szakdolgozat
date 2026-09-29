import json
import re

from bs4 import BeautifulSoup

import közös as KÖ
import konfiguracio as K
KIZART_RX = re.compile(K.KIZART, re.I)

def _lap_url(alap:str,mod:str,lap:int)->str:
    if mod=="path-page":
        return f"{alap}/" if lap == 1 else f"{alap}/page/{lap}/" #economx
    if lap==1:
        return alap
    if mod=="path":
        return f"{alap}/{lap}"
    return f"{alap}?page={lap}"

def _url_datum(url:str)->str|None:
    m = re.search(r"/(20\d\d)[-/_](\d{2})[-/_](\d{2})[-/_]", url + "/")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"/(20\d\d)(\d{2})(\d{2})[/_]", url + "/")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def cimke_egy_utotag(portal, cfg, utotag,rx, latott, max_lap)->list[dict]:
    alap=f"{cfg['cimke_alap'].rstrip('/')}/{utotag}"
    mod = cfg.get("lapozas", "query")
    ki: list[dict] = []
    ablak_alatt_sorozat = 0
    ures_lap = 0
    nincs_uj = 0

    for lap in range(1,max_lap+1):
        url=_lap_url(alap,mod,lap)
        try:
            resp=KÖ.KAPU.get(url)
            html=resp.text
        except Exception as e:
            print(f"    [{portal}/{utotag}] {lap}. lap hiba: {e}")
            break

        soup = BeautifulSoup(html, "lxml")
        szel = cfg.get("lista_szelektor")
        gyoker = soup.select(szel) if szel else [soup]
        talalt = []
        for elem in gyoker:
            for a in elem.find_all("a", href=True):
                u = a["href"].split("#")[0].split("?")[0]
                if u.startswith("//"):
                    u = "https:" + u
                elif u.startswith("/"):
                    u = cfg["base"].rstrip("/") + u
                if rx.search(u) and not KIZART_RX.search(u):
                    talalt.append(u)
        friss=[u for u in dict.fromkeys(talalt) if u not in latott]

        if not talalt:
            ures_lap += 1
            if ures_lap >= 2:
                if lap <= 2:
                    print(f"    [{portal}/{utotag}] nincs talalat (rossz utótag?) "
                          f"-> kihagyva")
                break
            continue
        ures_lap = 0

        if not friss:
            nincs_uj += 1
            if nincs_uj >= 2:
                break
            continue
        nincs_uj = 0
        latott.update(friss)

        lap_datumok = [d for u in talalt if (d := _url_datum(u))]
        alatt = sum(1 for d in lap_datumok if d < K.KEZDO_ABLAK)
        if lap_datumok and alatt >= 0.6 * len(lap_datumok):
            ablak_alatt_sorozat += 1
            if ablak_alatt_sorozat >= 3:
                break
        else:
            ablak_alatt_sorozat = 0

        lap_ablakban = 0
        for u in friss:
            d = _url_datum(u)
            if d is None or K.KEZDO_ABLAK <= d <= K.VEGSO_ABLAK:
                ki.append({"url": u, "sitemap_datum": d})
                lap_ablakban += 1

        if lap % 20 == 0:
            benne = [d for d in lap_datumok if K.KEZDO_ABLAK <= d <= K.VEGSO_ABLAK]
            print(f"    [{portal}/{utotag}] {lap}. lap ... eddig {len(ki)} URL "
                  f"(a lapon most: {min(benne) if benne else '2026 folott'})")

    return ki