import io
from datetime import date, timedelta

import közös as KÖ
import konfiguracio as K
import pandas as pd
from bs4 import BeautifulSoup
import re

ADATLETOLTES_URL = "https://www.portfolio.hu/adatletoltes"
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
    r = KÖ.KAPU.get(ADATLETOLTES_URL, robots=False)
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



def _koteslista_post(ticker:str,nap:str):
    token = _friss_token()
    adat = {
        "_token": token,
        "mode": "bse-boundslist",
        "boundlist-instrument": ticker,
        "boundlist-date": nap,
    }
    return KÖ.KAPU.post(LETOLTES_URL, robots=False, data=adat)


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


#def letolto_lepes():

#ef koteslista_felbonto():
