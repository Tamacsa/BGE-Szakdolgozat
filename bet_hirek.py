import re
import json


from bs4 import BeautifulSoup
from datetime import datetime,timezone
import os
import konfiguracio as K
import közös as KÖ
from dotenv import load_dotenv

load_dotenv()

API_SABLON=os.getenv("API_SABLON")
API_TORZS = {
    "query": "*",
    "facets": ["bet_date", "bet_type", "bet_issuer_f", "bet_tag",
               "newkib_subjectGroup", "newkib_newssubject"],
    "ddParams": [],
    "pageIndex": 0,
    "orderMode": "RELEVANCE",
    "category": "NEWS_NOT_BET",
    "contentPermission": ["READ"],
}


_RSPID_RX = re.compile(r"\$rspid[0-9a-fx]+")
_HO = {"jan": 1, "feb": 2, "már": 3, "mar": 3, "ápr": 4, "apr": 4, "máj": 5,
       "maj": 5, "jún": 6, "jun": 6, "júl": 7, "jul": 7, "aug": 8, "sze": 9,
       "okt": 10, "nov": 11, "dec": 12}

def proba_lepes(interaktiv: bool=False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("előbb telepítsd")
        return

    talalt=[]
    with sync_playwright() as p:
        b =p.chromium.launch(headless=not interaktiv)
        oldal=b.new_page(user_agent=K.UA, locale="hu-HU")

        def valaszolas(resp):
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            try:
                torzs=resp.text()
            except Exception:
                return
            keres=resp.request
            kerelem={
                "url": keres.url,
                "metodus": keres.method,
                "post_data": keres.post_data,
                "content_type": keres.headers.get("content-type"),
                "valasz_tipus": ("json" if torzs.lstrip()[:1] in "{["
                                 else "html" if torzs.lstrip()[:1] == "<"
                                 else "egyeb"),
                "valasz_meret": len(torzs),
            }
            ut_k=KÖ.ment_nyers("bet_proba",keres.url+'#req',
                               json.dumps(kerelem,ensure_ascii=False, indent=2),
                               "json")
            ut_v=KÖ.ment_nyers("bet_proba",keres.url, torzs,
                                "json" if kerelem["valasz_tipus"] == "json" else "html",)
            talalt.append((kerelem, ut_k, ut_v))

        oldal.on("response", valaszolas)
        oldal.goto(K.BET_KERESO, wait_until="networkidle", timeout=60_000)
        oldal.wait_for_timeout(4000)

        if interaktiv:
            print(">>> Írja be a kívánt filtereket, évszámokat és nyomjon ENTER-t.")
            input()
        else:
            for gomb in ("a[rel=next]", ".pagination .next a", "text=Következő"):
                try:
                    oldal.click(gomb, timeout=3000)
                    oldal.wait_for_timeout(3000)
                    break
                except Exception:
                    continue
        b.close()
        talalt.sort(key=lambda x: x[0]["valasz_tipus"], reverse=True)
        for n, ut_k, ut_v in talalt:
            print(f"\n{n['metodus']:<5} {n['valasz_meret']:>7} B  [{n['valasz_tipus']}]")
            print(f"  URL:    {n['url']}")
            if n["post_data"]:
                print(f"  TORZS:  {n['post_data'][:600]}")
            print(f"  keres:  {ut_k}\n  valasz: {ut_v}")


def _tokenek()->tuple[list[str], str]:
    r=KÖ.KAPU.get(K.BET_KERESO)
    soup=BeautifulSoup(r.content, "lxml")
    meta=soup.find("meta", attrs={"name":"_csrf"})
    csrf=meta.get("content") if meta else None
    jeloltek=list(dict.fromkeys(_RSPID_RX.findall(r.text)))
    if not (csrf and jeloltek):
        raise RuntimeError(
            f"nem található  token csrf==({bool(csrf)}, rspid={len(jeloltek)})"
        )
    fejlec=soup.find("meta", attrs={"name":"_csrf_header"})
    KÖ.KAPU.s.headers.update({
        (fejlec.get("content") if fejlec else "X-SECURITY"): csrf,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": K.BET_KERESO,
        "Origin": K.BET_BAZIS,

    })

    return jeloltek, csrf


def _keres(url: str, **mezok):
    return KÖ.KAPU.post(url, json=dict(API_TORZS, **mezok))

def _mukodo_url()->str:
    jeloltek, csrf = _tokenek()
    for rspid in jeloltek:
        url = API_SABLON.format(rspid=rspid, csrf=csrf)
        try:
            r=_keres(url)
            tetelek, _ = _elemek_valaszbol(r.text)
            if r.status_code == 200 and tetelek:
                print(f"mukodo portlet: {rspid}")
                return url
        except Exception as e:
            print(e)
            continue
    raise RuntimeError(
        f" A {len(jeloltek)} számó jelöl tegyike sem működött"

        )



def api_teszt_lepes():
    jeloltek, csrf = _tokenek()
    print(f"{len(jeloltek)} rspid-jelolt az oldalon: {jeloltek}\n")
    mukodo=None
    for rspid in jeloltek:
        url = API_SABLON.format(rspid=rspid, csrf=csrf)
        try:
            r=_keres(url)
            tetelek, pc=_elemek_valaszbol(r.text)
            allapot=f"HTTP {r.status_code}, {len(tetelek)} tetel, {pc} oldal"
            if r.status_code == 200 and tetelek and mukodo is None:
                mukodo=url
                allapot+=" <-- ez a kereso portlet"
        except Exception as e:
            allapot=f"HIBA {str(e)[:60]}"
        print(f" {rspid:<24}  {allapot}")

    if not mukodo:
        print("\n!! Egyik portlet sem válaszolt a találatokkal")
        print("A következőkben a Playwrightal kell folytatni")
        return

    print("\n A keresési alakok tesztje minden kibocsátüra vonatkozóan a működő portleten")
    for ticker, nev in K.BET_KIBOCSATOK.items():
        alap=nev.removesuffix(" Nyrt.").removesuffix(" Zrt.")
        print(f" [{ticker}] : {nev}")
        for cimke, k in [("csillag (bongeszo)", "*"),
                     ("pontos nev", nev),
                     ("idezojelben", f'"{nev}"'),
                     ("pont nelkul", alap),
                     ("config query", K.BET_KERES.get(ticker, nev))]:
            try:
                r=_keres(mukodo,query=k,pageIndex=0)
                tetelek, pc=_elemek_valaszbol(r.text)
                elso= tetelek[0]["kibocsato"] if tetelek else"-"
                jo=" OK " if elso == nev else "--"
                varhato=_szurok_szamlaloja(r.text,"bet_issuer_f",nev)
                print(f"{jo}{cimke:<18} HTTP {r.status_code} | "
                      f"{len(tetelek)} tétel | {pc} oldal | "
                      f" facet: {varhato}| elso kibocsatok: {elso}")
            except Exception as e:
                print(f"{cimke:<20} HIBA {str(e)[:70]}")
    print("\n-> Kibocsátónként az 'OK' alak a jó; ezt állítsa be a ")
    print("a BET_KERES és BET_KIBOCSATOK értékeknél" )



def _elemek_elemzese(adat_html: str )->dict|None:
    soup = BeautifulSoup(adat_html, "lxml")
    a= soup.find("a",href=True)
    if a is None:
        return None
    kib=soup.find(class_="issuer")
    dat=soup.find(class_="list-date")
    cim= soup.find(class_="title")
    href=a["href"]
    return{
        "url": href if href.startswith("http") else K.BET_BAZIS+href,
        "kibocsato":kib.get_text(" ",strip=True) if kib else None,
        "cim":cim.get_text(" ",strip=True) if cim else None,
        "lista_datum":dat.get_text(" ",strip=True) if dat else None,
    }

def _elemek_valaszbol(torzs: str) -> tuple[list[dict], int]:
    try:
        adat=json.loads(torzs)
    except Exception:
        return [],0
    if not isinstance(adat,dict) or "items" not in adat:
        return [],0
    tetelek=[t for t in(_elemek_elemzese(i.get("data", ""))
                      for i in adat["items"]) if t]
    return tetelek, int(adat.get("pageCount") or 0)

def _szurok_szamlaloja(torzs: str,mezo: str, ertek: str)->int:
    try:
        f=json.loads(torzs).get('facets',{}).get(mezo,[])
    except Exception:
        return 0
    return next((int(x.get("count") or 0)for x in f if x.get("value")==ertek),0)

def _relevans(t:dict)->bool:
    return (t.get("kibocsato") or "").strip() in K.BET_KIBOCSATOK.values()

def _lista_api(kezd:str, veg:str)->list[str]:
    url=_mukodo_url()
    osszes:dict[str,dict]={}
    facets = [f for f in API_TORZS["facets"] if f != "bet_issuer_f"]

    r0 = _keres(url, query="*", pageIndex=0)
    adat0 = json.loads(r0.text)
    facet_szamok = {x["value"]: x["count"] for x in adat0.get("facets", {}).get("bet_issuer_f", [])}

    for ticker, nev in K.BET_KIBOCSATOK.items():

        talalt,oldal,oldalszam,varhato=0,0,1,None
        print(f"\n[{ticker}] {nev}")

        while oldal <oldalszam and oldal<2000:
            try:
                r = _keres(url, query="*", facets=facets,
                           ddParams=[{"facet": "bet_issuer_f", "value": nev}],
                           pageIndex=oldal)
                r.raise_for_status()
            except Exception as e:
                print(f" {oldal}. oldal: {str(e)[:90]}")
                break

            tetelek, pc=_elemek_valaszbol(r.text)
            if oldal==0:
                oldalszam= pc or 1
                varhato = facet_szamok.get(nev, 0)
                print(f" {oldalszam} átnézendő "
                      f" és ebből {varhato} releváns tétel várható")
            if not tetelek:
                break

            for t in tetelek:
                if t['url'] not in osszes:
                    osszes[t['url']] = t
                    if _relevans(t):
                        talalt+=1
            oldal+=1

            if varhato and talalt>=varhato:
                print(f"  megvan mind a {talalt} tetel a {oldal}. oldalon "
                      f"(a {oldalszam}-bol) - leall")
                break
            if oldal % 25 ==0:
                print(f"{oldal}/{oldalszam} oldal | {talalt}"
                      + (f"/{varhato}" if varhato else "") + " relevans")
        if varhato and talalt < varhato:
            print(f"   HIÁNY: {talalt}/{varhato} - a lapozás korábban "
                  f"leállt, a korpusz nem teljes")
    return list(osszes.values())

def _lista_playwright(kezd=K.KEZDO_ABLAK, veg=K.VEGSO_ABLAK, max_oldal:int=5000)->list[dict]:
    from playwright.sync_api import sync_playwright
    osszes: dict[str, dict] = {}
    allapot = {"oldalak": 0}

    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        oldal = b.new_page(user_agent=K.UA, locale="hu-HU")

        def valaszra(resp):
            if "$risearch" not in resp.url:
                return
            try:
                tetelek,oldalszam=_elemek_valaszbol(resp.text())
            except Exception:
                return
            if not tetelek:
                return
            if oldalszam:
                allapot["oldalak"] = oldalszam
                for t in tetelek:
                    osszes.setdefault(t['url'], t)

        oldal.on('response', valaszra)
        oldal.goto(K.BET_KERESO,wait_until="networkidle", timeout=90_000)
        oldal.wait_for_timeout(3000)


        for sel in ("#onetrust-reject-all-handler", "text=Elutasít",
                    "text=Csak a szükséges"):
            try:
                oldal.click(sel,timeout=2000)
                break
            except Exception:
                continue
        print(f"  talalati oldalak: {allapot['oldalak']}, "
              f"elso oldal: {len(osszes)} tetel")

        lap=1
        while lap<min(allapot['oldalak'] or 1,max_oldal):
            elozo=len(osszes)
            kattintott=False
            for sel in ("a[rel=next]", ".pagination .next a",
                        ".pager-next a", "text=Következő"):

                try:
                    oldal.click(sel,timeout=4000)
                    kattintott=True
                    break
                except Exception:
                    continue
            if not kattintott:
                print("nincs tovább gombb a kattintás leáll")
                break
            oldal.wait_for_timeout(1000)
            lap+=1
            if len(osszes)==elozo:
                print(f"a {lap} oldal nem hozozz új tételt")
                break
            if lap%20==0:
                print(f"  {lap}/{allapot['oldalak']} oldal, {len(osszes)} tetel")
        b.close()
    return list(osszes.values())

def lepes_lista(kezd:str=K.KEZDO_ABLAK, veg: str= K.VEGSO_ABLAK, csak_relevans:bool = True):
    tetelek = (_lista_api(kezd, veg) if API_SABLON
               else _lista_playwright(kezd, veg))
    print(f"\n{len(tetelek)} tétel összesen")

    szurt=[t for t in tetelek if _relevans(t)] if csak_relevans else tetelek
    if csak_relevans:
        print(f"{len(szurt)} db tétel a négy kibocsátótól")
    vegleges=[]
    for t in szurt:
        dt, pont=_magyar_datum(t.get("lista_datum") or "")
        if dt is None:
            continue
        nap=dt.astimezone(K.IZ).date().isoformat()
        if kezd <=nap <= veg:
            t["megjelenes_utc"] = KÖ.iso(dt)
            t["ido_pontossag"] = pont
            vegleges.append(t)
    print(f"{len(vegleges)} tetel a {kezd} .. {veg} ablakban\n")

    con=KÖ.db()
    for t in vegleges:
        con.execute("INSERT OR IGNORE INTO naplo (url, statusz, hiba, ido) "
                    "VALUES (?, NULL, 'bet-varakozik', ?)",
                    (t['url'],KÖ.iso(datetime.now(timezone.utc))))
    con.executemany(
        "INSERT OR REPLACE INTO bet_lista_meta "
        "(url, megjelenes_utc, ido_pontossag, kibocsato, cim_lista) "
        "VALUES (:url, :megjelenes_utc, :ido_pontossag, :kibocsato, :cim)",
        vegleges)
    con.commit()
    KÖ.ment_nyers("bet", f"lista_{kezd}_{veg}",
                  json.dumps(vegleges,ensure_ascii=False, indent=2),"json")

    szamlalo = {}
    for t in vegleges:
        szamlalo[t["kibocsato"]] = szamlalo.get(t["kibocsato"], 0) + 1
    for k, n in sorted(szamlalo.items(), key=lambda x: -x[1]):
        print(f"  {k}: {n}")
    return vegleges



def _magyar_datum(s:str):
    m = re.search(r"(20\d{2})\.\s*([a-záéíóöőúüű]+)\.?\s*(\d{1,2})\.?"
                  r"(?:\s*(\d{1,2}):(\d{2}))?", s or "", re.I)

    if not m:
        return KÖ.ido_felbontas(s)
    ho=_HO.get(m.group(2)[:3].lower())
    if not ho:
        return None,"nincs"
    if m.group(4):
        dt = datetime(int(m.group(1)), ho, int(m.group(3)),
                      int(m.group(4)), int(m.group(5)))
        return KÖ.utc(dt), "perc"
    return KÖ.utc(datetime(int(m.group(1)), ho, int(m.group(3)))), "nap"