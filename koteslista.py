import io
from datetime import date, timedelta, datetime

import közös as KÖ
import konfiguracio as K
import pandas as pd
from bs4 import BeautifulSoup
import re
import requests

ADATLETOLTES_URL = "https://www.portfolio.hu/adatletoltes"
_TOKEN = None

def _token(frissit: bool = False) -> str:
    global _TOKEN
    if _TOKEN is None or frissit:
        _TOKEN = _friss_token()
    return _TOKEN
LETOLTES_URL = "https://www.portfolio.hu/adatletoltes/letoltes"

SZUNNAPOK = {
    "2024-01-01", "2024-03-29", "2024-04-01", "2024-05-01", "2024-05-20",
    "2024-08-20", "2024-10-23", "2024-11-01", "2024-12-24", "2024-12-25",
    "2024-12-26", "2024-12-31",
    "2025-01-01", "2025-04-18", "2025-04-21", "2025-05-01", "2025-06-09",
    "2025-08-20", "2025-10-23", "2025-11-01", "2025-12-24", "2025-12-25",
    "2025-12-26", "2025-12-31",
    "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01", "2026-05-25",
    "2026-08-20", "2026-10-23", "2026-12-24", "2026-12-25", "2026-12-31",
}

def kereskedesi_napok(kezd:str,veg:str):
    d,v=date.fromisoformat(kezd),date.fromisoformat(veg)
    while d<=v:
        if d.weekday()<5 and d.isoformat() not in SZUNNAPOK:
            yield d.isoformat()
        d+=timedelta(days=1)

def _friss_token()->str:
    r = KÖ.KAPU.get(ADATLETOLTES_URL)
    soup = BeautifulSoup(r.text, "lxml")
    meta = soup.find("meta", attrs={"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]
    form = soup.find("form", id="boundlistForm")
    if form:
        inp = form.find("input", attrs={"name": "_token"})
        if inp and inp.get("value"):
            return inp["value"]
    raise RuntimeError("Nem talalhato csrf-token az /adatletoltes oldalon - "
                       "valtozott az oldal szerkezete, vagy a sutik lejartak.")


def _cookie_betoltes():
    KÖ.sutik_betolt(K.COOKIE_FAJL, alap_domain="portfolio.hu")
    return KÖ.KAPU



def _koteslista_post(ticker: str, nap: str, frissit: bool = False):
    adat = {
        "_token": _token(frissit),
        "mode": "bse-boundslist",
        "boundlist-instrument": ticker,
        "boundlist-date": nap,
    }
    return KÖ.KAPU.post(LETOLTES_URL, data=adat)

def proba_lepes(ticker:str,nap:str | None=None):
    _cookie_betoltes()
    nap = nap or next(kereskedesi_napok(
        (date.today() - timedelta(days=7)).isoformat(),
        date.today().isoformat()))
    r = _koteslista_post(ticker, nap)
    ctype = r.headers.get("Content-Type", "")
    cdisp = r.headers.get("Content-Disposition", "")
    print(f"HTTP {r.status_code} | Content-Type: {ctype} | "
          f"Content-Disposition: {cdisp} | {len(r.content)} B")

    if "html" in ctype.lower():
        ut = KÖ.ment_nyers("koteslista", f"{ticker}-{nap}-html", r.text)
        print(f"!! HTML jott xlsx helyett -> {ut}")
        if "bejelentkez" in r.text.lower() or "előfizet" in r.text.lower():
            print("!! Az oldal bejelentkezest/elofizetest kert -> "
                  "a sutik lejartak, vagy nincs erre jogosultsag az elofizetesben.")
        return
    ut = KÖ.ment_nyers_bin("koteslista", f"{ticker}-{nap}", r.content, kiterj="xlsx")
    print(f"-> {ut}")
    try:
        xl = pd.ExcelFile(io.BytesIO(r.content))
        print(f"Munkalapok: {xl.sheet_names}")
        for lap in xl.sheet_names:
            df = xl.parse(lap, header=None, nrows=15)
            print(f"\n--- [{lap}] elso 15 sor, nyers (fejléc nelkul) ---")
            print(df.to_string())
    except Exception as e:
        print(f"!! Nem sikerult xlsx-kent beolvasni: {e}")

def _fejlec_sor_keres(df_nyers: pd.DataFrame) -> int | None:
    for i in range(min(20, len(df_nyers))):
        sor = " ".join(str(v).lower() for v in df_nyers.iloc[i].tolist())
        van_ido = any(k in sor for k in ("idő", "ido", "time"))
        van_ar = any(k in sor for k in ("ár", "arfolyam", "price"))
        if van_ido and van_ar:
            return i
    return None

_SZAM = re.compile(r"[^\d,.\-]")

def _szam(s):
    s = _SZAM.sub("", str(s)).replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def koteslista_felbonto_xlsx(xlsx_bytes: bytes, ticker: str, nap: str)->list[dict]:
    xl = pd.ExcelFile(io.BytesIO(xlsx_bytes))
    for lap in xl.sheet_names:
        nyers=xl.parse(lap, header=None)
        fejlec_i=_fejlec_sor_keres(nyers)
        if fejlec_i is None:
            continue
        df = xl.parse(lap, header=fejlec_i)
        oszl={str(c).strip().lower(): c for c in df.columns}
        ido_o = next((v for k, v in oszl.items()
                      if "idő" in k or "ido" in k or "time" in k), None)
        ar_o = next((v for k, v in oszl.items()
                     if k.startswith("ár") or k == "ar" or "price" in k
                     or "árfolyam" in k), None)
        db_o = next((v for k, v in oszl.items()
                     if "darab" in k or "mennyi" in k or "volume" in k
                     or "kötésszám" in k or "kotesszam" in k), None)
        forg_o = next((v for k, v in oszl.items()
                       if "forgalom" in k or "érték" in k or "ertek" in k), None)
        if not (ido_o and ar_o):
            continue
        sorok=[]
        for i, r in df.iterrows():
            ido = str(r[ido_o]).strip()
            m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", ido)
            if not m:
                continue
            dt = datetime.fromisoformat(nap).replace(
                hour=int(m.group(1)), minute=int(m.group(2)),
                second=int(m.group(3) or 0))
            ar = _szam(r[ar_o])
            db = _szam(r[db_o]) if db_o else None
            forg = _szam(r[forg_o]) if forg_o else None
            sorok.append({
                "ticker": ticker, "nap": nap, "sorszam": int(i),
                "ts_utc": KÖ.iso(KÖ.utc(dt)), "ar": ar, "mennyiseg": db,
                "ertek": forg if forg is not None else
                ((ar * db) if (ar and db) else None),
            })
        if len(df) > 0 and not sorok:
            raise ValueError("nincs ertelmezheto idopont egyik sorban sem")
        sorok.reverse()
        for n, s in enumerate(sorok, start=1):
            s["sorszam"] = n
        return sorok
    raise ValueError("nincs fejlec egyik munkalapon sem")


def letolto_lepes(kezd=K.KEZDO_ABLAK, veg=K.VEGSO_ABLAK, tickerek=None):
    _cookie_betoltes()
    con = KÖ.db()
    tickerek = tickerek or list(K.TICKEREK)
    napok = list(kereskedesi_napok(kezd, veg))
    print(f"{len(tickerek)} ticker x {len(napok)} nap = "
          f"{len(tickerek) * len(napok)} lekeres")
    html_egymas = 0
    for ticker in tickerek:
        for nap in napok:
            kulcs = f"koteslista:{ticker}:{nap}"
            if KÖ.mar_letoltve(con, kulcs):
                continue
            try:
                try:
                    r = _koteslista_post(ticker, nap)
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 419:
                        r = _koteslista_post(ticker, nap, frissit=True)
                    else:
                        raise
                if "html" in r.headers.get("Content-Type", "").lower():
                    html_egymas += 1
                    print(f"  {ticker} {nap}: HTML jott xlsx helyett "
                          f"({html_egymas}/3)")
                    if html_egymas >= 3:
                        raise RuntimeError(
                            "3 egymas utani HTML valasz - a sutik lejartak, "
                            "exportald ujra a sutit, majd futtasd ujra.")
                    continue
                html_egymas = 0
                KÖ.ment_nyers_bin("koteslista", f"{ticker}-{nap}",
                                  r.content, kiterj="xlsx")
                sorok = koteslista_felbonto_xlsx(r.content, ticker, nap)
                if sorok:
                    con.executemany(
                        "INSERT OR REPLACE INTO kotes "
                        "(ticker,nap,sorszam,ts_utc,ar,mennyiseg,ertek) "
                        "VALUES (:ticker,:nap,:sorszam,:ts_utc,:ar,"
                        ":mennyiseg,:ertek)", sorok)
                KÖ.naplo(con, kulcs, 200, "" if sorok else "ures")
                con.commit()
                print(f"  {ticker} {nap}: {len(sorok)} kotes")
            except RuntimeError:
                raise
            except Exception as e:
                KÖ.naplo(con, kulcs, -1, str(e))
                con.commit()
                print(f"  {ticker} {nap}: HIBA {str(e)[:80]}")
    print("kesz.")



    