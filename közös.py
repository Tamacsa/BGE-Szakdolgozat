from datetime import datetime, timezone
import re
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


