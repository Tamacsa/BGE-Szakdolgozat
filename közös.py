import gzip
import hashlib
import json
import time
from datetime import datetime, timezone
import re
import math
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

from pathlib import Path
import requests
import unicodedata

import konfiguracio as K
from dateutil import parser as datumfelbonto



#időzónaátváltás
def utc(dt:datetime | None) -> datetime|None:
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
    s= str(nyers)
    if re.search(r"\d{1,2}:\d{2}:\d{2}", s):
        pont= "masodperc"
    elif re.search(r"\d{1,2}:\d{2}", s):
        pont= "perc"
    else:
        pont= "nap"
    return utc(dt),pont

_GYENGE,_EROS,_KIZARO={},{},{}
for t,d,in K.TICKEREK.items():
    _EROS[t] = [re.compile(p) for p in d["eros"]]
    _GYENGE[t]= [re.compile(p, re.IGNORECASE) for p in d["gyenge"]]
    _KIZARO[t]=[re.compile(p, re.IGNORECASE) for p in K.RELEVANS_KIZARO.get(t,[])]
_PIACI = [re.compile(p, re.I) for p in K.RELEVANS_PIACI]
_MIND ={t: _EROS[t]+ _GYENGE[t] for t in K.TICKEREK}

def _piaci_kontextus(szoveg:str| None) -> bool:
    s=(szoveg or "")[:K.RELEVANS_PIACI_MAX_KAR]
    return any(r.search(s) for r in _PIACI)


def tickerek(cim_lead: str, teljes: str) ->tuple[list[str], list[str]]:
    cim_lead = cim_lead or ""
    teljes = teljes or ""

    if not _piaci_kontextus(teljes):
        return [], []
    eros, gyenge=[],[]

    for t in K.TICKEREK:
        if any(r.search(teljes) for r in _KIZARO[t]):
            continue
        mind= _MIND[t]
        if any(r.search(cim_lead) for r in mind):
            eros.append(t)
        elif any(r.search(teljes) for r in mind):
            gyenge.append(t)
    return eros, gyenge

_HORGONY_SZAM= re.compile(r"\d[\d\u00a0 .,]{1,}\d|\d{3,}")
_HORGONY_NEV = re.compile(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][A-ZÁÉÍÓÖŐÚÜŰ0-9]{1,}\b"
                          r"|\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]{3,}\b")
_HORGONY_STOP={
    "@rendkí", "@tájéko", "@budape", "@magyar", "@szerző", "@csatol",
    "@nyrt", "@zrt", "@kft", "@english", "@version",
}

def horgonyok(szoveg: str| None) -> frozenset[str]:
    s=szoveg or ""
    ki=set()
    for m in _HORGONY_SZAM.finditer(s):
        t = re.sub(r"[\u00a0 .,]", "", m.group())
        if len(t)>=3:
            ki.add("#" +(t.lstrip("0") or "0"))
    for m in _HORGONY_NEV.finditer(s):
        t=unicodedata.normalize("NFKC", m.group()).lower()[:6]
        if len(t)>=3:
            ki.add("@"+t)
    return frozenset(ki-_HORGONY_STOP)

def horgony_idf(halmazok)->dict[str, float]:
    halmazok=list(halmazok)
    n=max(1,len(halmazok))
    gyak: dict[str, float] = {}
    for h in halmazok:
        for t in h:
            gyak[t]=gyak.get(t,0)+1
    return {t: math.log(n/(1+c)) for t, c in gyak.items()}

def horgony_pont(a:frozenset[str], b:frozenset[str], idf: dict[str, float])->float:
    kozos=a&b
    if not kozos:
        return 0.0
    alap=max(idf.values(),default=1)
    sulyoz= lambda h: sum(idf.get(t,alap) for t in h)
    nevezo=min(sulyoz(a),sulyoz(b))
    return (sulyoz(kozos)/nevezo) if nevezo> 0 else 0.0

def par_tipus(a_forras:str,b_forras:str)->str:
    a_bet,b_bet=a_forras=="bet",b_forras=="bet"
    if a_bet and b_bet:
        return "bet->bet"
    if a_bet:
        return "bet->portal"
    if b_bet:
        return "portal->bet"
    if a_forras==b_forras:
        return "azonos portal"
    return"portal->portal"


def ervenyes_par(a_forras:str,b_forras:str)->bool:
    if b_forras=="bet":
        return False
    if a_forras==b_forras:
        return False
    return True

def kereszt_forrasu(tipus:str)->bool:
    return tipus in ("bet->portal","portal->portal")


#Szövegnormalizálás

_ZAJ= re.compile(r"(kapcsolódó cikk|hirdetés|fotó:|forrás:|címlapkép|"
    r"iratkozzon fel|kövesse a|további cikkeink)",re.IGNORECASE)

def normalizal(s: str | None)-> str:
    s=unicodedata.normalize("NFC", s or "").lower()
    s=re.sub(r"https?://\S+", " ", s)
    s=_ZAJ.sub(" ", s)
    s=re.sub(r"[^0-9a-záéíóöőúüű ]+", " ", s)
    return re.sub(r"\s+", " ",s).strip()

_BET_FEJLEC = re.compile( r"^.{0,80}?\d{4}\.\s*\S+\s*\d{1,2}\.\s*\d{1,2}:\d{2}\s*Szerz[őo]:\s*")
_BET_CSATOLMANY=re.compile(r"Csatolt dokumentumok:(?:\s*[\w.\-]+\.pdf\s*\(\d+\s*kB\))+", re.IGNORECASE)
_BET_SABLON=re.compile(r"(English version"
    r"|Stratégiai és Pénzügyi Divízió Befektetői Kapcsolatok"
    r"|Hivatkozási szám:\s*\S+"
    r"|Tel(?:efon)?\.?:\s*\+?[\d\s/\-]{6,}"
    r"|Fax:\s*\+?[\d\s/\-]{6,})", re.IGNORECASE)

def bet_szoveg_tisztit(s:str| None)-> str:
    s=re.sub(r"\s+"," ", str(s or "").replace("\u00a0"," ")).strip()
    s=_BET_FEJLEC.sub("", s)
    s=_BET_CSATOLMANY.sub(" ", s)
    s=_BET_SABLON.sub(" ", s)
    return re.sub(r"\s+"," ", s).strip()


def hash_szoveg(s:str| None)-> str | None:
    n= normalizal(s)
    return hashlib.sha1(n.encode()).hexdigest() if n else None

def doc_id(url:str)->str:
    return hashlib.sha1(url.encode()).hexdigest()[:20]


class Kapu:
    def __init__(self):
        self._rp: dict[str, RobotFileParser | None] = {}
        self._delay: dict[str, float]={}
        self._utolso: dict[str, float]={}
        self.s= requests.Session()
        self.s.headers.update({
            "User-Agent":K.UA,
            "Accept-Language": "hu-HU,hu;q=0.9",
            "Accept-Encoding": "gzip, deflate",

        })

    def _robots(self, url: str) -> RobotFileParser | None:
        host=urlparse(url).netloc
        if host in self._rp:
            return self._rp[host]
        try:
            r=self.s.get(urljoin(f"https://{host}","/robots.txt"), timeout=K.TIMEOUT)
            (K.ADAT/f"robots_{host}.txt").write_text(r.text,encoding="utf-8")
            rp=RobotFileParser()
            rp.parse(r.text.splitlines())
            cd=rp.crawl_delay(K.UA)
            self._delay[host]=max(K.ALAP_KESLELTETES, float(cd or 0))
        except Exception:
            rp=None
            self._delay[host]=K.ALAP_KESLELTETES
        self._rp[host]=rp
        return rp

    def szabad(self,url:str)-> bool:
        rp=self._robots(url)
        return True if rp is None else rp.can_fetch(K.UA,url)

    def _var(self, url: str):
        host= urlparse(url).netloc
        d=self._delay.get(host, K.ALAP_KESLELTETES)
        eltelt=time.monotonic()-self._utolso.get(host,0)
        if eltelt < d:
            time.sleep(d-eltelt)
        self._utolso[host]=time.monotonic()



    def get(self, url:str, robots= True, probak=3, **kwargs):
        if robots and not self.szabad(url):
            raise PermissionError(f"robots.txt tiltja: {url}")
        utolso=None
        for i in range(probak):
            self._var(url)
            try:
                r = self.s.get(url, timeout=K.TIMEOUT, **kwargs)
                if 400<=r.status_code<500:
                    r.raise_for_status()
                r.raise_for_status()
                return r
            except requests.HTTPError as e:
                if e.response is not None and 400<=e.response.status_code<500:
                    raise
                utolso=e
            except Exception as e:
                utolso = e
            if i <probak-1:
                time.sleep(2**(i+1))
        raise utolso

    def post(self, url:str, robots= True, probak=3, **kwargs):
        if robots and not self.szabad(url):
            raise PermissionError(f"robots.txt tiltja: {url}")
        utolso = None
        for i in range(probak):
            self._var(url)
            try:
                r = self.s.post(url, timeout=K.TIMEOUT, **kwargs)
                if 400<=r.status_code<500:
                    r.raise_for_status()
                r.raise_for_status()
                return r
            except requests.HTTPError as e:
                if e.response is not None and 400<=e.response.status_code<500:
                    raise
                utolso=e
            except Exception as e:
                utolso = e
            if i <probak-1:
                time.sleep(2**(i+1))
        raise utolso


    def xml(self, url:str, **kwargs)->bytes:
        r=self.get(url, **kwargs)
        b=r.content
        if url.endswith(".gz") or b[:2]==b"\x1f\x8b":
            b=gzip.decompress(b)
        return b
KAPU=Kapu()

def sutik_betolt(fajl, alap_domain:str=".portfolio.hu")->int:
    fajl=Path(fajl)
    if not fajl.exists():
        raise SystemExit(f"{fajl.name} nem létezik")
    adat=json.loads(fajl.read_text(encoding="utf-8"))
    if isinstance(adat, dict):
        adat=[{"name":k, "value":v} for k,v in adat.items()]

    alap_suffix=alap_domain.lstrip(".")
    n= 0
    for c in adat:
        if not c.get("name"):
            continue
        dom = str(c.get("domain")or alap_domain).strip()
        if dom == alap_suffix or dom.endswith("." + alap_suffix) or dom == alap_domain:
            dom = alap_domain
        KAPU.s.cookies.set(c["name"], c.get("value",""), domain=dom)
        n+=1
    return n


