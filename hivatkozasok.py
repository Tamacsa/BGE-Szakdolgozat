import re
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import konfiguracio as K
import közös as KÖ
import portalok

_ELEJE_BLOKK_DB = 2
_ZAJ_HOST = re.compile(
    r"(gemius|google\.|facebook\.|twitter\.|x\.com|instagram\.|youtube\.|youtu\.be|"
    r"linkedin\.|shop\.telex|forum\.portfolio|profil\.portfolio|trader\.portfolio|"
    r"terminal\.portfolio)", re.I)
_PORTFOLIO_CIKK = re.compile(r"/\d{8}/")
_BET_ID = re.compile(r"/(\d{8,10})(?:/|$)|_(\d{8,10})(?:$|\.)")
_TELEX_CIKK = re.compile(r"/20\d\d/\d\d/\d\d/")
_FORRAS_JELZES = re.compile(
    r"(írja|írták|megírta|közölte|közölték|közleményében|jelentette|beszámol|"
    r"idézi|nyomán|értesülés|tájékoztat|hivatkoz|jelent meg)", re.I)


def _norm(url: str) -> str:
    p = urlparse(url)
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def _bet_id(url: str) -> str | None:
    return (m.group(1) or m.group(2)) if (m := _BET_ID.search(urlparse(url).path)) else None


class _Feloldo:
    def __init__(self, con):
        self.url, self.portfolio_id, self.bet = {}, {}, {}
        for r in con.execute("SELECT doc_id, forras, url FROM dokumentum"):
            d, f, u = r["doc_id"], r["forras"], r["url"]
            if f == "bet":
                if b := _bet_id(u): self.bet[b] = d
            else:
                self.url[_norm(u)] = d
                if f == "portfolio" and (m := re.search(r"-(\d+)$", urlparse(u).path)):
                    self.portfolio_id[m.group(1)] = d

    def feloldas(self, url: str):
        p = urlparse(url)
        host, path = p.netloc.lower().removeprefix("www."), p.path
        if host.endswith("bet.hu"):
            return "bet", self.bet.get(_bet_id(url) or "")
        if host.endswith("portfolio.hu"):
            if not _PORTFOLIO_CIKK.search(path): return None, None
            m = re.search(r"-(\d+)$", path)
            return "portfolio", self.url.get(_norm(url)) or (self.portfolio_id.get(m.group(1)) if m else None)
        if host.endswith("telex.hu"):
            return ("telex", self.url.get(_norm(url))) if _TELEX_CIKK.search(path) else (None, None)
        if not host or _ZAJ_HOST.search(host):
            return None, None
        return "kulso", None


def _blokkok(forras: str, soup: BeautifulSoup):
    if forras == "portfolio":
        if lead := soup.select_one(".pfarticle-section-lead"):
            yield "lead", lead
        elemek = list(portalok._torzs_elemek(soup))
    else:
        tarolo = soup.select_one(".article-html-content")
        elemek = tarolo.find_all(["p", "ul", "ol", "blockquote"]) if tarolo else []
    for i, e in enumerate(elemek):
        yield ("torzs_eleje" if i < _ELEJE_BLOKK_DB else "torzs"), e


def cikk_hivatkozasok(doc_id: str, forras: str, html: str, feloldo: _Feloldo) -> list[dict]:
    soup, ki = BeautifulSoup(html, "lxml"), {}
    alap = "https://www.portfolio.hu" if forras == "portfolio" else "https://telex.hu"
    for hely, elem in _blokkok(forras, soup):
        bekezdes = elem.get_text(" ", strip=True)
        jel = _FORRAS_JELZES.search(bekezdes)
        for a in elem.find_all("a", href=True):
            cel = urljoin(alap, a["href"].strip())
            if not cel.startswith("http"): continue
            cel_forras, cel_doc = feloldo.feloldas(cel)
            if not cel_forras or cel_doc == doc_id: continue

            if cel_forras == "bet":
                tipus = "forras"
            elif cel_forras == forras:
                tipus = "forras" if jel and hely != "torzs" else "hatter"
            else:
                tipus = "forras" if hely != "torzs" or jel else "hatter"

            kulcs = _norm(cel)
            if kulcs not in ki or (ki[kulcs]["tipus"] == "hatter" and tipus == "forras"):
                ki[kulcs] = {"doc_id": doc_id, "cel_url": cel, "cel_doc_id": cel_doc,
                             "cel_forras": cel_forras, "tipus": tipus, "hely": hely,
                             "horgony_szoveg": a.get_text(" ", strip=True)[:120]}
    return list(ki.values())


def lepes_hivatkozas():
    con = KÖ.db()
    feloldo = _Feloldo(con)
    sorok = con.execute(
        "SELECT doc_id, forras, raw_path FROM dokumentum "
        "WHERE forras IN ('portfolio','telex') ORDER BY doc_id").fetchall()
    print(f"{len(sorok)} cikk hivatkozásainak kinyerése ...")

    con.execute("DELETE FROM hivatkozas")
    osszes = Counter()

    for i, r in enumerate(sorok, 1):
        p = K.BAZIS / r["raw_path"] if r["raw_path"] else None
        if not p or not p.exists():
            osszes["nincs_nyers"] += 1
            continue

        hiv = cikk_hivatkozasok(r["doc_id"], r["forras"], p.read_text(encoding="utf-8"), feloldo)
        con.executemany(
            "INSERT OR REPLACE INTO hivatkozas VALUES (?,?,?,?,?,?,?)",
            [(h["doc_id"], h["cel_url"], h["cel_doc_id"], h["cel_forras"],
              h["tipus"], h["hely"], h["horgony_szoveg"]) for h in hiv])
        osszes.update((h["cel_forras"], h["tipus"]) for h in hiv)

        if i % 500 == 0:
            con.commit()
            print(f"  {i}/{len(sorok)}")

    con.commit()
    print("\nKinyert hivatkozások (cél, típus):")
    for k, v in sorted(osszes.items(), key=lambda x: str(x[0])):
        print(f"  {k}: {v}")

    n, = con.execute("SELECT COUNT(DISTINCT doc_id) FROM hivatkozas WHERE tipus='forras'").fetchone()
    b, = con.execute("SELECT COUNT(*) FROM hivatkozas WHERE cel_doc_id IS NOT NULL AND tipus='forras'").fetchone()
    print(f"\n{n} cikknek van forrás-hivatkozása; ebből {b} link mutat a korpuszban "
          f"lévő dokumentumra (ezek a biztos 'nem új' párok).")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lepes_hivatkozas()