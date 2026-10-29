import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import közös as KÖ
import konfiguracio as K
KIZART_RX = re.compile(K.KIZART, re.I)
MIN_SZO=K.MIN_TORZS_SZO
MAX_CSONKA_SOR = 5

_SZEMET_ATTR = re.compile(
    r"(hirdet|advert|\bads?\b|banner|promo|sponsor|"
    r"newsletter|hirlevel|feliratkoz|"
    r"(?<!non-)paywall|premium|signature|elofizet|subscribe|regisztraci|"
    r"kapcsolod|related|ajanlo|recommend|olvasta-mar|tovabbi-cikk|"
    r"social|megosztas|share|comment|hozzaszol|"
    r"cookie|consent|sidebar|breadcrumb|"
    r"konferencia|conference|event-box|investment-day|"
    r"cimke|tag-list|author-box|szerzo-box)"

    , re.I)

_SZEMET_TAG=("script", "style", "noscript", "iframe", "form", "svg",
               "nav", "aside", "footer", "template")


_PROMO_SOR = re.compile(
    r"(Investment Day|Információ és jelentkezés|Szakértőink minden kérdésre"
    r"|Portfolio Signature|előfizetői program"
    r"|Iratkozz(?:on)? fel|Hírlevél|Kövess(?:e|en)? (?:minket|a )"
    r"|Kapcsolódó cikk|Címlapkép|^Fotó:|^Forrás: (?:Shutterstock|Getty|MTI)"
    r"|Nyitókép:|Elolvasom|Jelentkezem|Regisztrálok)", re.I)


def _lap_url(alap:str,mod:str,lap:int)->str:
    if lap==1:
        return alap
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
    latott_itt: set[str] = set()

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
        uj_itt = [u for u in dict.fromkeys(talalt) if u not in latott_itt]
        friss = [u for u in uj_itt if u not in latott]

        if not talalt:
            ures_lap += 1
            if ures_lap >= 2:
                if lap <= 2:
                    print(f"    [{portal}/{utotag}] nincs találat (rossz utótag?) "
                          f"-> kihagyva")
                break
            continue
        ures_lap = 0

        if not uj_itt:
            nincs_uj += 1
            if nincs_uj >= 2:
                print(f"    [{portal}/{utotag}] {lap}. lapnál ismétlődés -> leáll")
                break
            continue
        nincs_uj = 0
        latott_itt.update(uj_itt)
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

MIN_TORZS_ROVID = 25
_CIKK_TORZS = "article.pfarticle .pfarticle-section-content"
_TORZS_SZOVEG_TAG = ("p", "ul", "ol", "h2", "h3", "h4", "blockquote")
_TORZS_KIHAGY = re.compile(
    r"(disclaimer|conference|adocean|inline-chart|chart-|related|"
    r"trader-ad|newsletter|hirlevel)", re.I)

def _torzs_elemek(soup:BeautifulSoup):
    """A cikk tárolójának szöveges blokkjai (p, ul/ol, alcím, idézet), sorrendben.
    A reklám-, grafikon-, ajánló- és jogi blokkokat kihagyja. A szöveg-kinyerés
    és a hivatkozás-kinyerés (hivatkozasok.py) is ezt használja, hogy mindkettő
    pontosan ugyanazt a törzset lássa."""
    kontener = soup.select_one(_CIKK_TORZS)
    if kontener is None:
        return

    def bejar(elem):
        for gyerek in elem.find_all(recursive=False):
            osztaly = " ".join(gyerek.get("class") or []) + " " + str(gyerek.get("id") or "")
            if _TORZS_KIHAGY.search(osztaly):
                continue
            if gyerek.name in _TORZS_SZOVEG_TAG:
                yield gyerek
            elif gyerek.name == "div":
                yield from bejar(gyerek)

    yield from bejar(kontener)

def _torzs_szoveg(soup:BeautifulSoup)->str|None:
    sorok: list[str] = []
    for elem in _torzs_elemek(soup):
        if elem.name in ("ul", "ol"):
            sorok.extend(li.get_text(" ", strip=True) for li in elem.find_all("li"))
        else:
            sorok.append(elem.get_text(" ", strip=True))
    return "\n".join(s for s in sorok if s) or None

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

    if (torzs := _torzs_szoveg(nyers_soup)):
        szurt = _promo_szures(torzs)
        if _szohossz(szurt) >= MIN_TORZS_ROVID:
            return szurt, "cikk-torzs"

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


def _idobelyeg(soup):
    jeloltek=[
        ("article:published_time",
         soup.find("meta", property="article:published_time")),
        ("og:published_time", soup.find("meta", property="og:published_time")),
        ("itemprop:datePublished",
         soup.find(attrs={"itemprop": "datePublished"})),
        ("time[datetime]", soup.find("time", attrs={"datetime": True})),
    ]

    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            adat=json.loads(sc.string or "{}")
        except Exception:
            continue
        halom = adat if isinstance(adat, list) else [adat]
        while halom:
            it = halom.pop()
            if isinstance(it, dict):
                if "@graph" in it:
                    halom+=it["@graph"] or[]
                if it.get("datePublished"):
                    dt,pont=KÖ.ido_felbontas(it["datePublished"])
                    if dt:
                        return dt,pont,"json-ld"

    for cimke,tag in jeloltek:
        if tag is None:
            continue
        ertek = (tag.get("content") or tag.get("datetime")
                 or tag.get_text(strip=True))
        dt,pont=KÖ.ido_felbontas(ertek)
        if dt:
            return dt,pont,cimke

    return None, "nincs", None

def cikk_elemzo(html:str,url:str,portal:str)->dict:
    soup = BeautifulSoup(html, "lxml")
    megj,pont,ido_forras=_idobelyeg(soup)

    mod_tag=soup.find("meta", property="article:modified_time")
    mod,_=KÖ.ido_felbontas(mod_tag.get("content") if mod_tag else None)

    og = soup.find("meta", property="og:title")
    cim = (og.get("content") if og and og.get("content")
           else (soup.title.get_text(strip=True) if soup.title else None))

    ogd = soup.find("meta", property="og:description")
    lead = ogd.get("content") if ogd and ogd.get("content") else None

    szoveg,sz_forras=kinyer_szoveg(html)

    fejlec = " ".join(filter(None, [cim, lead]))
    teljes = " ".join(filter(None, [cim, lead, szoveg]))
    eros, gyenge = KÖ.tickerek(fejlec, teljes)

    return {
        "doc_id": KÖ.doc_id(url), "forras": portal, "tipus": "cikk", "url": url,
        "cim": cim, "lead": lead, "szoveg": szoveg,
        "szohossz": _szohossz(szoveg),
        "megjelenes_utc": KÖ.iso(megj),
        "megjelenes_helyi": megj.astimezone(K.IZ).isoformat() if megj else None,
        "ido_forras": ido_forras, "ido_pontossag": pont,
        "modositas_utc": KÖ.iso(mod),
        "ticker_eros": eros, "ticker_gyenge": gyenge,
        "norm_hash": KÖ.hash_szoveg(teljes), "szoveg_forras": sz_forras,
        "letoltve": KÖ.iso(datetime.now(timezone.utc)),
    }


def _portal_url(url:str)->str:
    u_host = urlparse(url).netloc.removeprefix("www.")
    for p, cfg in K.PORTALOK.items():
        if u_host == urlparse(cfg["base"]).netloc.removeprefix("www."):
            return p
    return "?"

def lepes_letolt(limit=None, portal=None):
    con=KÖ.db()
    q="SELECT url FROM naplo WHERE (statusz IS NULL or statusz = 0)"
    if portal:
        host = urlparse(K.PORTALOK[portal]["base"]).netloc.removeprefix("www.")
        q += f" AND url LIKE '%{host}%'"
    if limit:
        q += f" LIMIT {int(limit)}"
    sor=con.execute(q).fetchall()

    for p in ([portal] if portal else list(K.PORTALOK)):
        _portal_sutik(p)
    print(f"{len(sor)} cikk letöltése...")

    szamlalo=Counter()
    csonka_sor = 0
    for i,r in enumerate(sor,1):
        url=r["url"]
        try:
            resp = KÖ.KAPU.get(url)
            rec = cikk_elemzo(resp.text, url, _portal_url(url))

            if rec["szoveg"] is None:
                KÖ.naplo(con, url, 0, f"csonka:{rec['szoveg_forras']}:{len(resp.text)}")
                szamlalo["csonka"] += 1
                csonka_sor += 1
                if csonka_sor >= MAX_CSONKA_SOR:
                    print(f"{csonka_sor} csonka oldal egymás után - "
                          f"a süti valószínűleg lejárt. Exportálj újat, "
                          f"majd futtasd újra.")
                    break
                continue
            csonka_sor = 0
            rec["raw_path"] = KÖ.ment_nyers(rec["forras"], url, resp.text)
            KÖ.ment_dokumentum(con, rec)
            KÖ.naplo(con, url, resp.status_code)
            szamlalo[rec["szoveg_forras"] or "nincs"] += 1
        except Exception as e:
            KÖ.naplo(con, url, getattr(getattr(e, "response", None),
                                      "status_code", -1), str(e))
            szamlalo["HIBA"] += 1
        if i % 25==0:
            con.commit()
            print(f"  {i}/{len(sor)}  {dict(szamlalo)}")
    con.commit()
    print("kesz.", dict(szamlalo))



def lepes_felderites(portal=None, max_lap=800):
    con = KÖ.db()
    tetelek = ([(portal, K.PORTALOK[portal])] if portal
               else list(K.PORTALOK.items()))
    for p, cfg in tetelek:
        print(f"\n[{p}] felderítés...")
        try:
            urls = felderit_cimke(p, cfg, max_lap)
        except Exception as e:
            print(f"  [{p}] HIBA: {e}")
            continue
        for u in urls:
            con.execute(
                "INSERT OR IGNORE INTO naplo (url, statusz, hiba, ido) "
                "VALUES (?, NULL, 'varakozik', ?)",
                (u["url"], KÖ.iso(datetime.now(timezone.utc))))
        con.commit()
    n = con.execute("SELECT COUNT(*) c FROM naplo WHERE statusz IS NULL"
                    ).fetchone()["c"]
    print(f"\n-> {n} letöltendő URL a sorban.")