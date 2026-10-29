import hashlib
import json
import time
from datetime import datetime, timezone
import re
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import sqlite3

from pathlib import Path
import requests
import unicodedata

import konfiguracio as K
from dateutil import parser as datumfelbonto


# időzónaátváltás
def utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=K.IZ)
    return dt.astimezone(timezone.utc)


def ido_felbontas(nyers: str | None):
    if not nyers:
        return None, "nincs"
    try:
        dt = datumfelbonto.parse(str(nyers))
    except Exception:
        return None, "nincs"
    if dt is None:
        return None, "nincs"
    s = str(nyers)
    if re.search(r"\d{1,2}:\d{2}:\d{2}", s):
        pont = "masodperc"
    elif re.search(r"\d{1,2}:\d{2}", s):
        pont = "perc"
    else:
        pont = "nap"
    return utc(dt), pont


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


_GYENGE, _EROS, _KIZARO = {}, {}, {}
for t, d, in K.TICKEREK.items():
    _EROS[t] = [re.compile(p) for p in d["eros"]]
    _GYENGE[t] = [re.compile(p, re.IGNORECASE) for p in d["gyenge"]]
    _KIZARO[t] = [re.compile(p, re.IGNORECASE) for p in K.RELEVANS_KIZARO.get(t, [])]
_PIACI = [re.compile(p, re.I) for p in K.RELEVANS_PIACI]
_MIND = {t: _EROS[t] + _GYENGE[t] for t in K.TICKEREK}


def _piaci_kontextus(szoveg: str | None) -> bool:
    s = (szoveg or "")[:K.RELEVANS_PIACI_MAX_KAR]
    return any(r.search(s) for r in _PIACI)


def tickerek(cim_lead: str, teljes: str) -> tuple[list[str], list[str]]:
    cim_lead = cim_lead or ""
    teljes = teljes or ""
    piaci = _piaci_kontextus(teljes)
    eros, gyenge = [], []

    for t in K.TICKEREK:
        if any(r.search(teljes) for r in _KIZARO[t]):
            continue
        mind = _MIND[t]
        if any(r.search(cim_lead) for r in mind):
            eros.append(t)
        elif piaci and any(r.search(teljes) for r in mind):
            gyenge.append(t)
    return eros, gyenge


_ZAJ = re.compile(r"(kapcsolódó cikk|hirdetés|fotó:|forrás:|címlapkép|"
                  r"iratkozzon fel|kövesse a|további cikkeink)", re.IGNORECASE)


def normalizal(s: str | None) -> str:
    s = unicodedata.normalize("NFC", s or "").lower()
    s = re.sub(r"https?://\S+", " ", s)
    s = _ZAJ.sub(" ", s)
    s = re.sub(r"[^0-9a-záéíóöőúüű ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_BET_FEJLEC = re.compile(r"^.{0,80}?\d{4}\.\s*\S+\s*\d{1,2}\.\s*\d{1,2}:\d{2}\s*Szerz[őo]:\s*")
_BET_CSATOLMANY = re.compile(r"Csatolt dokumentumok:(?:\s*[\w.\-]+\.pdf\s*\(\d+\s*kB\))+", re.IGNORECASE)
_BET_SABLON = re.compile(r"(English version"
                         r"|Stratégiai és Pénzügyi Divízió Befektetői Kapcsolatok"
                         r"|Hivatkozási szám:\s*\S+"
                         r"|Tel(?:efon)?\.?:\s*\+?[\d\s/\-]{6,}"
                         r"|Fax:\s*\+?[\d\s/\-]{6,})", re.IGNORECASE)


def bet_szoveg_tisztit(s: str | None) -> str:
    s = re.sub(r"\s+", " ", str(s or "").replace("\u00a0", " ")).strip()
    s = _BET_FEJLEC.sub("", s)
    s = _BET_CSATOLMANY.sub(" ", s)
    s = _BET_SABLON.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def hash_szoveg(s: str | None) -> str | None:
    n = normalizal(s)
    return hashlib.sha1(n.encode()).hexdigest() if n else None


def doc_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:20]


class Kapu:
    def __init__(self):
        self._rp: dict[str, RobotFileParser | None] = {}
        self._delay: dict[str, float] = {}
        self._utolso: dict[str, float] = {}
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": K.UA,
            "Accept-Language": "hu-HU,hu;q=0.9",
            "Accept-Encoding": "gzip, deflate",

        })

    def _robots(self, url: str) -> RobotFileParser | None:
        host = urlparse(url).netloc
        if host in self._rp:
            return self._rp[host]
        try:
            r = self.s.get(urljoin(f"https://{host}", "/robots.txt"), timeout=K.TULLEPES)
            (K.ADAT / f"robots_{host}.txt").write_text(r.text, encoding="utf-8")
            rp = RobotFileParser()
            rp.parse(r.text.splitlines())
            cd = rp.crawl_delay(K.UA)
            self._delay[host] = max(K.ALAP_KESLELTETES, float(cd or 0))
        except Exception:
            rp = None
            self._delay[host] = K.ALAP_KESLELTETES
        self._rp[host] = rp
        return rp

    def szabad(self, url: str) -> bool:
        rp = self._robots(url)
        return True if rp is None else rp.can_fetch(K.UA, url)

    def _var(self, url: str):
        host = urlparse(url).netloc
        d = self._delay.get(host, K.ALAP_KESLELTETES)
        eltelt = time.monotonic() - self._utolso.get(host, 0)
        if eltelt < d:
            time.sleep(d - eltelt)
        self._utolso[host] = time.monotonic()

    def get(self, url: str, robots=True, probak=3, **kwargs):
        if robots and not self.szabad(url):
            raise PermissionError(f"robots.txt tiltja: {url}")
        utolso = None
        for i in range(max(1, probak)):
            self._var(url)
            try:
                r = self.s.get(url, timeout=K.TULLEPES, **kwargs)
                r.raise_for_status()
                return r
            except requests.HTTPError as e:
                kod = e.response.status_code if e.response is not None else None
                if kod is not None and kod not in (408, 429) and 400 <= kod < 500:
                    raise
                utolso = e
                if i < probak - 1 and e.response is not None:
                    try:
                        time.sleep(min(int(e.response.headers.get("Retry-After", 0)), 60))
                    except ValueError:
                        pass
            except Exception as e:
                utolso = e
            if i < probak - 1:
                time.sleep(2 ** (i + 1))
        raise utolso

    def post(self, url: str, robots=True, probak=3, **kwargs):
        if robots and not self.szabad(url):
            raise PermissionError(f"robots.txt tiltja: {url}")
        utolso = None
        for i in range(max(1, probak)):
            self._var(url)
            try:
                r = self.s.post(url, timeout=K.TULLEPES, **kwargs)
                r.raise_for_status()
                return r
            except requests.HTTPError as e:
                kod = e.response.status_code if e.response is not None else None
                if kod is not None and kod not in (408, 429) and 400 <= kod < 500:
                    raise
                utolso = e
                if i < probak - 1 and e.response is not None:
                    try:
                        time.sleep(min(int(e.response.headers.get("Retry-After", 0)), 60))
                    except ValueError:
                        pass
            except Exception as e:
                utolso = e
            if i < probak - 1:
                time.sleep(2 ** (i + 1))
        if utolso:
            raise utolso
        raise RuntimeError("Váratlan hiba a kérés során")


KAPU = Kapu()


def sutik_betolt(fajl, alap_domain: str = ".portfolio.hu") -> int:
    fajl = Path(fajl)
    if not fajl.exists():
        raise SystemExit(f"{fajl.name} nem létezik")
    adat = json.loads(fajl.read_text(encoding="utf-8"))
    if isinstance(adat, dict):
        adat = [{"name": k, "value": v} for k, v in adat.items()]

    alap_suffix = alap_domain.lstrip(".")
    n = 0
    for c in adat:
        if not c.get("name"):
            continue
        dom = str(c.get("domain") or alap_domain).strip()
        if dom == alap_suffix or dom.endswith("." + alap_suffix) or dom == alap_domain:
            dom = alap_domain
        KAPU.s.cookies.set(c["name"], c.get("value", ""), domain=dom)
        n += 1
    return n


SEMA = """
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS dokumentum (
    doc_id          TEXT PRIMARY KEY,
    forras          TEXT NOT NULL,
    tipus           TEXT NOT NULL,
    url             TEXT UNIQUE NOT NULL,
    cim             TEXT,
    lead            TEXT,
    szoveg          TEXT,
    szohossz        INTEGER DEFAULT 0,
    megjelenes_utc  TEXT,
    megjelenes_helyi TEXT,
    ido_forras      TEXT,
    ido_pontossag   TEXT,
    modositas_utc   TEXT,
    ticker_eros     TEXT,
    ticker_gyenge   TEXT,
    norm_hash       TEXT,
    szoveg_forras   TEXT,
    raw_path        TEXT,
    letoltve        TEXT,
    bet_tipus       TEXT
  );   
     CREATE INDEX IF NOT EXISTS dok_ido ON dokumentum(megjelenes_utc);
     CREATE INDEX IF NOT EXISTS dok_forras ON dokumentum(forras);
     CREATE INDEX IF NOT EXISTS dok_hash ON dokumentum(norm_hash);

    CREATE TABLE IF NOT EXISTS naplo (
    url             TEXT PRIMARY KEY,
    statusz         INTEGER,
    hiba            TEXT,
    ido             TEXT
    );

    CREATE TABLE IF NOT EXISTS bet_lista_meta (
    url             TEXT PRIMARY KEY,
    megjelenes_utc   TEXT,
    ido_pontossag   TEXT,
    kibocsato       TEXT,
    cim_lista       TEXT
    );

    CREATE TABLE IF NOT EXISTS kotes(
    ticker         TEXT NOT NULL,
    nap            TEXT NOT NULL,
    sorszam        INTEGER NOT NULL,
    ts_utc         TEXT NOT NULL,
    ar             REAL,
    mennyiseg      REAL,
    ertek          REAL,
    PRIMARY KEY (ticker, nap, sorszam) 
    );

    CREATE INDEX IF NOT EXISTS kotes_ts ON kotes(ticker, ts_utc);

    CREATE TABLE IF NOT EXISTS beagyazas (
    doc_id         TEXT NOT NULL,
    modell         TEXT NOT NULL,
    vek            BLOB NOT NULL,
    PRIMARY KEY (doc_id, modell) 
    );

    CREATE TABLE IF NOT EXISTS hivatkozas (
    doc_id          TEXT NOT NULL,
    cel_url         TEXT NOT NULL,
    cel_doc_id      TEXT,
    cel_forras      TEXT NOT NULL,
    tipus           TEXT NOT NULL,
    hely            TEXT NOT NULL,
    horgony_szoveg  TEXT,
    PRIMARY KEY (doc_id, cel_url)
    );

    CREATE INDEX IF NOT EXISTS hiv_cel ON hivatkozas(cel_doc_id);

    CREATE TABLE IF NOT EXISTS regi_hir (
    doc_id          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    osztaly         TEXT NOT NULL,
    osztaly_szoveg  TEXT NOT NULL,
    regi_arany      REAL,
    kozeli_arany    REAL,
    kozeli_doc_id   TEXT,
    szomszedok      TEXT,
    hivatkozott     TEXT,
    szoveg_db       INTEGER,
    jelolt_db       INTEGER,
    indok           TEXT NOT NULL,
    kulso_forras    INTEGER DEFAULT 0,
    PRIMARY KEY (doc_id, ticker)
    );

    CREATE TABLE IF NOT EXISTS bux_kosar (
    ervenyes_tol    TEXT NOT NULL,
    hivatkozasi_nap TEXT,
    ticker          TEXT NOT NULL,
    q               REAL NOT NULL,
    ff              REAL NOT NULL,
    wf              REAL NOT NULL,
    suly_kosarban_pct REAL,
    forras          TEXT,
    PRIMARY KEY (ervenyes_tol, ticker)
    );

    CREATE TABLE IF NOT EXISTS piaci_suly (
    nap             TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    kosar_tol       TEXT NOT NULL,
    elozo_zaras     REAL,
    ertek           REAL,
    suly            REAL,
    PRIMARY KEY (nap, ticker)
    );

    CREATE TABLE IF NOT EXISTS perc_idosor (
    ticker          TEXT NOT NULL,
    nap             TEXT NOT NULL,
    perc            INTEGER NOT NULL,
    ts_utc          TEXT NOT NULL,
    ar_utolso       REAL,
    ar_vwap         REAL,
    mennyiseg       REAL,
    kotes_db        INTEGER,
    kitoltott       INTEGER,
    hozam           REAL,
    piaci_hozam     REAL,
    ar              REAL,
    av_atlag        REAL,
    av              REAL,
    PRIMARY KEY (ticker, nap, perc)
    );

    CREATE TABLE IF NOT EXISTS esemeny (
    doc_id          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    forras          TEXT NOT NULL,
    osztaly         TEXT NOT NULL,
    osztaly_szoveg  TEXT,
    t0_utc          TEXT NOT NULL,
    t0_tipus        TEXT NOT NULL,
    nap             TEXT NOT NULL,
    kezdo_perc      INTEGER NOT NULL,
    car_kezdeti     REAL,
    car_kesleltetett REAL,
    cav_kezdeti     REAL,
    kesl_percek     INTEGER,
    figyelem        REAL,
    PRIMARY KEY (doc_id, ticker)
    );
    """


def db() -> sqlite3.Connection:
    con = sqlite3.connect(K.ADATBAZIS, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SEMA)
    con.commit()
    return con


def ment_dokumentum(con, rec: dict):
    rec = dict(rec)
    for k in ("ticker_eros", "ticker_gyenge"):
        if isinstance(rec.get(k), (list, tuple)):
            rec[k] = json.dumps(rec[k], ensure_ascii=False)
    oszlopok = [r[1] for r in con.execute("PRAGMA table_info(dokumentum)")]
    rec = {k: v for k, v in rec.items() if k in oszlopok}
    if "doc_id" in rec and "norm_hash" in rec:
        regi = con.execute("SELECT norm_hash FROM dokumentum WHERE doc_id=?",
                           (rec["doc_id"],)).fetchone()
        if regi and regi["norm_hash"] != rec["norm_hash"]:
            con.execute("DELETE FROM beagyazas WHERE doc_id=?", (rec["doc_id"],))
    q = (f"INSERT OR REPLACE INTO dokumentum({','.join(rec)}) "
         f"VALUES ({','.join('?' * len(rec))})")
    con.execute(q, list(rec.values()))


def naplo(con, url, statusz=None, hiba=None):
    con.execute("INSERT OR REPLACE INTO naplo VALUES (?,?,?,?)",
                (url, statusz, (hiba or "")[:300], iso(datetime.now(timezone.utc))))


def mar_letoltve(con, url) -> bool:
    r = con.execute("SELECT statusz FROM naplo WHERE url=?", (url,)).fetchone()
    return bool(r and r['statusz'] == 200)


def ment_nyers(alkonytar: str, kulcs: str, tartalom: str, kiterj="html") -> str:
    d = K.NYERS / alkonytar
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{hashlib.md5(kulcs.encode('utf-8')).hexdigest()[:12]}.{kiterj}"
    p.write_text(tartalom, encoding="utf-8")
    return str(p.relative_to(K.BAZIS))


def ment_nyers_bin(alkonytar: str, kulcs: str, tartalom: bytes, kiterj="pdf") -> str:
    d = K.NYERS / alkonytar
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{hashlib.md5(kulcs.encode('utf-8')).hexdigest()[:12]}.{kiterj}"
    p.write_bytes(tartalom)
    return str(p.relative_to(K.BAZIS))


if __name__ == "__main__":
    import shutil

    K.ADATBAZIS = K.ADAT / "teszt.sqlite"
    con = db()
    url = "https://pelda.hu/cikk"
    rec = {"doc_id": doc_id(url), "forras": "portfolio", "tipus": "cikk",
           "url": url, "cim": "Teszt cím",
           "ticker_eros": ["OTP", "MOL"], "nincs_ilyen_oszlop": 123}
    ment_dokumentum(con, rec)
    ment_dokumentum(con, rec)
    con.commit()
    db_sor = con.execute("SELECT COUNT(*) FROM dokumentum").fetchone()[0]
    assert db_sor == 1, f"{db_sor} db sor van"
    tarolt = con.execute("SELECT ticker_eros FROM dokumentum").fetchone()["ticker_eros"]
    assert json.loads(tarolt) == ["OTP", "MOL"], tarolt
    print("ment_dokumentum: rendben (1 sor, lista visszaolvasható, ismeretlen kulcs eldobva)")

    assert mar_letoltve(con, url) is False
    naplo(con, url, 404, "nem található")
    assert mar_letoltve(con, url) is False
    naplo(con, url, 200)
    assert mar_letoltve(con, url) is True
    print("mar_letoltve: rendben (False -> 404 -> False -> 200 -> True)")

    p1 = ment_nyers('_teszt', url, "<html>ő ű</html>")
    p2 = ment_nyers('_teszt', url, "<html>ő ű</html>")
    assert p1 == p2, (p1, p2)
    assert not Path(p1).is_absolute()
    assert (K.BAZIS / p1).exists()
    assert (K.BAZIS / p1).read_text(encoding="utf-8") == "<html>ő ű</html>"
    p3 = ment_nyers_bin("_teszt", url, b"%PDF-1.4", "pdf")
    assert p3.endswith(".pdf") and (K.BAZIS / p3).read_bytes() == b"%PDF-1.4"
    print("ment_nyers*: rendben (azonos útvonal, relatív, tartalom megvan):", p1)

    con.close()
    K.ADATBAZIS.unlink()
    shutil.rmtree(K.NYERS / "_teszt")
    print("Minden teszt rendben, takarítás kész")