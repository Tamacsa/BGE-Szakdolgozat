import re
import json
from bs4 import BeautifulSoup
from datetime import datetime,timezone
import os
import konfiguracio as K
import közös as KÖ
from dotenv import load_dotenv

load_dotenv()

API_SABLON=os.getenv("API_SABLON","https://www.valami.hu/kereso/{rspid}/$risearch?_csrf={csrf}")
API_TORZS= {
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

def _elemek_valaszbol(valami):

    return valami

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
                varhato=_facet_szam(r.text,"bet_issuer_f",nev)
                print(f"{jo}{cimke:<18} HTTP {r.status_code} | "
                      f"{len(tetelek)} tétel | {pc} oldal | "
                      f" facet: {varhato}| elso kibocsatok: {elso}")
            except Exception as e:
                print(f"{cimke:<20} HIBA {str(e)[:70]}")
    print("\n-> Kibocsátónként az 'OK' alak a jó; ezt állítsa be a ")
    print("a BET_KERES és BET_KIBOCSATOK értékeknél" )

def _facet_szam(valami, valami2, valami3):
    pass
