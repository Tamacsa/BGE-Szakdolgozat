from pathlib import Path
from zoneinfo import ZoneInfo


BAZIS=Path(__file__).resolve().parent
ADAT=BAZIS/"adat"
NYERS=BAZIS/"nyers"
ADATBAZIS=ADAT/"korpusz.sqlite"

IZ=ZoneInfo("Europe/Budapest")

TICKEREK = {
    "OTP":{
        "nev":"OTP Bank Nyrt.",
        "isin":"HU0000061726",
        "eros":[r"\bOTP\b"],
        "gyenge":[r"\bOTP[ \-]?(csoport|Bank|Group)\b"],
    },
    "MOL":{
        "nev":"MOL Nyrt.",
        "isin":"HU0000153937",
        "eros":[r"\bMOL\b"],
        "gyenge":[r"\bMOL[ \-]?(Nyrt|csoport|részvény|papír)",
                r"\bMagyar Olaj[- ]és Gázipari\b"],
    },
    "RICHTER":{
        "nev":"Richter Gedeon Nyrt.",
        "isin":"HU0000123096",
        "eros":[r"\bRICHTER\b"],
        "gyenge":[r"\b(Gdeon )? Richter\w*"],
    },
    "MTELEKOM":{
        "nev":"OTP Bank Nyrt.",
        "isin":"HU0000061726",
        "eros":[r"\bOTP\b"],
        "gyenge":[r"\bOTP\b"],
    }


}