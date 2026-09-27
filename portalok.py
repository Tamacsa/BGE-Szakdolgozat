import json
import re
import közös as KŐ
import konfiguracio as K


def _lap_url(alap:str,mod:str,lap:int)->str:
    if mod=="path-page":
        return f"{alap}/" if lap == 1 else f"{alap}/page/{lap}/" #economx
    if lap==1:
        return alap
    if mod=="path":
        return f"{alap}/{lap}"
    return f"{alap}?page={lap}"