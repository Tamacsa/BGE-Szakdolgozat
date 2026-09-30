import json
import re

import requests
from bs4 import BeautifulSoup

import közös as KÖ
import konfiguracio as K
KIZART_RX = re.compile(K.KIZART, re.I)

_SZEMET_ATTR = re.compile(
    r"(hirdet|advert|\bads?\b|banner|promo|sponsor|"
    r"newsletter|hirlevel|feliratkoz|"
    r"paywall|premium|signature|elofizet|subscribe|regisztraci|"
    r"kapcsolod|related|ajanlo|recommend|olvasta-mar|tovabbi-cikk|"
    r"social|megosztas|share|comment|hozzaszol|"
    r"cookie|consent|sidebar|breadcrumb|"
    r"konferencia|conference|event-box|investment-day|"
    r"cimke|tag-list|author-box|szerzo-box)", re.I)

_SZEMET_TAG=("script", "style", "noscript", "iframe", "form", "svg",
               "nav", "aside", "footer", "template")

def _lap_url(alap:str,mod:str,lap:int)->str:
    if mod=="path-page":
        return f"{alap}/" if lap == 1 else f"{alap}/page/{lap}/" #economx
    if lap==1:
        return alap
    if mod=="path":
        return f"{alap}/{lap}"

    if mod =="query-oldal":
        return f"{alap}?oldal={lap}"
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

def _takarit(html:str)->BeautifulSoup:
    soup=BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_SZEMET_TAG):
        if not tag.decomposed:
            tag.decompose()
    for tag in soup.find_all(attrs={"class": True}):
        if not tag.decomposed and _SZEMET_ATTR.search(
                " ".join(tag.get("class") or [])):
            tag.decompose()
    for tag in soup.find_all(attrs={"id": True}):
        if not tag.decomposed and _SZEMET_ATTR.search(str(tag.get("id") or "")):
            tag.decompose()

    return soup

def felderit_cimke(portal:str, cfg:dict, max_lap:int=800)->list[dict]:
    rx=re.compile(cfg["cikk_regex"])
    utotagok=cfg["cimke_utotag"] or []
    latott:set[str]=set()
    ki: list[dict]=[]
    for utotag in utotagok:
        db= cimke_egy_utotag(portal,cfg,utotag,rx,latott,max_lap)
        ki+=db
        print(f"    [{portal}/{utotag}] {len(db)} cikk-URL az ablakban")
    print(f"  [{portal}] cimke-bejáras kész: {len(ki)} cikk-URL "
              f"({len(utotagok)} utótag)")
    return ki

def kinyer_szoveg(html:str)->tuple[str|None,str]:
    nyers_soup = BeautifulSoup(html, "lxml")
    tiszta_soup = _takarit(html)
    tiszta_html = str(tiszta_soup)
