import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import közös as KÖ
import konfiguracio as K
KIZART_RX = re.compile(K.KIZART, re.I)
MIN_SZO=K.MIN_TORZS_SZO

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


_PROMO_SOR = re.compile(
    r"(Investment Day|Információ és jelentkezés|Szakértőink minden kérdésre"
    r"|Portfolio Signature|előfizetői program"
    r"|Iratkozz(?:on)? fel|Hírlevél|Kövess(?:e|en)? (?:minket|a )"
    r"|Kapcsolódó cikk|Címlapkép|^Fotó:|^Forrás: (?:Shutterstock|Getty|MTI)"
    r"|Nyitókép:|Elolvasom|Jelentkezem|Regisztrálok)", re.I)


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
def _jsonld_body(soup:BeautifulSoup)->str|None:
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            adat=json.loads(sc.string or "{}")
        except Exception:
            continue
        halom=adat if isinstance(adat, list) else [adat]
        while halom:
            it=halom.pop()
            if not isinstance(it, dict):
                continue
            if "@graph" in it:
                halom+=it["@graph"] or []
            torzs=it.get("articleBody")
            if isinstance(torzs, str) and torzs.strip():
                return torzs.strip()
    return None
def _trafi(html: str)->str|None:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        return trafilatura.extract(html, include_comments=False, include_tables=False)
    except Exception:
        return None
def _tag_szoveg(soup:BeautifulSoup)->str|None:
    jeloltek = (
        soup.find(attrs={"itemprop": "articleBody"}),
        soup.find("article"),
        soup.find("main"),
    )
    for tag in jeloltek:
        if tag is None:
            continue
        bekezdesek=[p.get_text(" ", strip=True) for p in tag.find_all("p")]
        szoveg="\n".join(b for b in bekezdesek if b)
        if not szoveg:
            szoveg=tag.get_text("\n", strip=True)
        if _szohossz(szoveg)>= MIN_SZO:
            return szoveg
    return None
def _szohossz(szoveg: str | None)->int:
    return len(str(szoveg or "").split())

def _promo_szures(szoveg: str | None)->str:
    sorok=[s.strip() for s in str(szoveg or "").splitlines()]
    megtartott= [s for s in sorok if s and not _PROMO_SOR.search(s)]
    return "\n".join(megtartott).strip()

_SUTIK_BETOLTVE: set[str] = set()

def _portal_sutik(portal:str)->bool:
    if portal in _SUTIK_BETOLTVE:
        return True
    fajl=K.PORTAL_SUTIK.get(portal)
    if not fajl or not fajl.exists():
        return False
    cfg=K.PORTALOK.get(portal) or {}
    host = urlparse(cfg.get("base", "")).netloc.removeprefix("www.")
    n=KÖ.sutik_betolt(fajl,alap_domain=f".{host}" if host else ".portfolio.hu")
    print(f"[{portal}] {n} süti betöltve ({fajl.name})")
    _SUTIK_BETOLTVE.add(portal)
    return True

def kinyer_szoveg(html:str)->tuple[str|None,str]:
    nyers_soup = BeautifulSoup(html, "lxml")
    tiszta_soup = _takarit(html)
    tiszta_html = str(tiszta_soup)

    jeloltek:list[tuple[str,str]]=[]
    if (b:=_jsonld_body(nyers_soup)):
        jeloltek.append(("json-ld", b))
    if(t:=_trafi(tiszta_html)):
        jeloltek.append(("trafilatura", t))
    if (t2:=_trafi(html)):
        jeloltek.append(("trafilatura-nyers", t2))
    if (s := _tag_szoveg(tiszta_soup)):
        jeloltek.append(("selector", s))
    ertekelt=[]
    for nev, szoveg in jeloltek:
        szurt=_promo_szures(szoveg)
        ertekelt.append({"nev":nev, "szurt":szurt, "szo":_szohossz(szurt)})
    tisztak=[j for j in ertekelt if j["szo"]>=MIN_SZO]
    if tisztak:
        nyertes = max(tisztak, key=lambda j: j["szo"])
        return nyertes["szurt"], nyertes["nev"]
    if not jeloltek:
        return None, "nincs-jelolt"
    return None, "rovid"


