from datetime import datetime, timezone
import re

import unicodedata

import konfiguracio as K
from dateutil import parser as datumfelbonto
import tzdata


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

def _HORGONY(szoveg: str| None) -> frozenset[str]:
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

if __name__ == "__main__":
    print(_HORGONY("Rendkívüli tájékoztatás. Az OTP Bank Nyrt. részvényeinek árfolyama 39.000 forint volt."))