from datetime import datetime, timezone
import re
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




