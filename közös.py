from datetime import datetime, timezone
import re
import math
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
