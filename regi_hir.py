import json
import re
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime

import snowballstemmer

import konfiguracio as K
import közös as KÖ

_TOKEN = re.compile(r"[^\W_]+")
_TOVEZO = snowballstemmer.stemmer("hungarian")
_TOVEK: dict[str, str] = {}

_STOP = frozenset("""a az egy és hogy is nem de van volt lesz lett már még meg el ki be fel le át
ez ezt ezek az azt azok ami amely amelyek amit aki mint vagy ha csak által szerint után előtt
között alatt felé során illetve valamint ezzel azzal ebben abban erre arra ide oda itt ott
így úgy miatt ellen óta is sem se mert mivel ezért azért pedig viszont azonban tehát
én te ő mi ti ők őket nekik neki nekem vele rá rá ról ről től tól hoz hez höz nak nek ban ben
ra re ba be val vel ért ig kor""".split())


def szotovek(szoveg: str) -> frozenset[str]:
    ki = set()
    for t in _TOKEN.findall((szoveg or "").lower()):
        if t in _STOP or (len(t) < 2 and not t.isdigit()):
            continue
        if not t.isdigit() and t not in _TOVEK:
            _TOVEK[t] = _TOVEZO.stemWord(t)
        ki.add(t if t.isdigit() else _TOVEK[t])
    return frozenset(ki)


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class _Dok:
    __slots__ = ("doc_id", "forras", "ts", "kulcs", "szavak", "tickerek", "helyi_nap")

    def __init__(self, r):
        self.doc_id, self.forras = r["doc_id"], r["forras"]
        self.ts = _ts(r["megjelenes_utc"])
        self.kulcs = (self.ts, 0 if self.forras == "bet" else 1, self.doc_id)
        torzs = KÖ.bet_szoveg_tisztit(r["szoveg"]) if self.forras == "bet" else (r["szoveg"] or "")
        self.szavak = szotovek(f"{r['cim'] or ''} {r['lead'] or ''} {torzs}")
        self.tickerek = sorted({t for o in K.REGI_TICKER_OSZLOPOK for t in json.loads(r[o] or "[]")})
        self.helyi_nap = (r["megjelenes_helyi"] or r["megjelenes_utc"])[:10]


def _betolt(con):
    dokok = {r["doc_id"]: _Dok(r) for r in con.execute(
        "SELECT doc_id, forras, cim, lead, szoveg, megjelenes_utc, megjelenes_helyi, "
        "ticker_eros, ticker_gyenge FROM dokumentum WHERE megjelenes_utc IS NOT NULL "
        "AND szoveg IS NOT NULL")}

    forras_link = defaultdict(list)
    kulso = set()
    for r in con.execute("SELECT doc_id, cel_doc_id, cel_forras FROM hivatkozas WHERE tipus='forras'"):
        if r["cel_doc_id"]:
            forras_link[r["doc_id"]].append(r["cel_doc_id"])
        elif r["cel_forras"] == "kulso":
            kulso.add(r["doc_id"])

    return dokok, forras_link, kulso


def _meres(s: _Dok, jeloltek: list[_Dok]):
    n = len(s.szavak)
    pontok = []
    for c in jeloltek:
        if kozos := len(s.szavak & c.szavak):
            pontok.append((kozos, c.kulcs, c))

    if not pontok:
        return 0.0, 0.0, []

    pontok.sort(key=lambda x: (x[0], x[1]), reverse=True)
    pontok = pontok[:K.REGI_SZOMSZED_DB]
    unio = set().union(*(s.szavak & c.szavak for _, _, c in pontok))

    return len(unio) / n, pontok[0][0] / n, [c for _, _, c in pontok]


def _osztaly(old: float, kozeli: float) -> str:
    if old < K.REGI_KUSZOB:
        return "uj"
    return "atvetel" if kozeli / old > K.REGI_ATVETEL_KUSZOB else "ujrakombinalt"


def osztalyoz(dokok, forras_link, kulso):
    ablak = K.REGI_ABLAK_ORA * 3600
    ticker_dokok = defaultdict(list)
    for d in dokok.values():
        for t in d.tickerek:
            ticker_dokok[t].append(d)

    sorok = []
    for t, lista in ticker_dokok.items():
        lista.sort(key=lambda d: d.kulcs)
        idok = [d.ts for d in lista]
        for i, s in enumerate(lista):
            alap = {"doc_id": s.doc_id, "ticker": t, "szoveg_db": len(s.szavak),
                    "kulso_forras": int(s.doc_id in kulso), "hivatkozott": "[]",
                    "szomszedok": "[]", "regi_arany": None, "kozeli_arany": None,
                    "kozeli_doc_id": None, "jelolt_db": 0}


            if s.forras == "bet":
                sorok.append({**alap, "osztaly": "uj", "osztaly_szoveg": "uj", "indok": "bet"})
                continue


            kezd = bisect_left(idok, s.ts - ablak)
            jeloltek = [c for c in lista[kezd:i] if c.kulcs < s.kulcs]
            alap["jelolt_db"] = len(jeloltek)

            if len(s.szavak) < K.REGI_MIN_SZO:
                sorok.append({**alap, "osztaly": "rovid", "osztaly_szoveg": "rovid", "indok": "szoveg"})
                continue


            old, kozeli, szomszedok = _meres(s, jeloltek)
            osztaly_szoveg = _osztaly(old, kozeli)
            osztaly, indok = osztaly_szoveg, "szoveg"


            kotelezo = [c for c in forras_link.get(s.doc_id, []) if c in dokok and dokok[c].kulcs < s.kulcs]
            if kotelezo:
                if osztaly_szoveg == "uj":
                    osztaly = "atvetel" if len(kotelezo) == 1 else "ujrakombinalt"
                    indok = "hivatkozas"
                else:
                    indok = "szoveg+hivatkozas"

            sorok.append({**alap, "osztaly": osztaly, "osztaly_szoveg": osztaly_szoveg,
                          "regi_arany": old, "kozeli_arany": kozeli,
                          "kozeli_doc_id": szomszedok[0].doc_id if szomszedok else None,
                          "szomszedok": json.dumps([c.doc_id for c in szomszedok]),
                          "hivatkozott": json.dumps(kotelezo), "indok": indok})
    return sorok


def lepes_regi_hir():
    con = KÖ.db()
    dokok, forras_link, kulso = _betolt(con)
    print(f"{len(dokok)} dokumentum betöltve, szótövezés kész: {len(_TOVEK)} különböző szó")
    sorok = osztalyoz(dokok, forras_link, kulso)

    con.execute("DROP TABLE IF EXISTS regi_hir")
    con.executescript(KÖ.SEMA)

    if sorok:
        oszlopok = list(sorok[0])
        helyek = ",".join(["?"] * len(oszlopok))
        con.executemany(f"INSERT INTO regi_hir ({','.join(oszlopok)}) VALUES ({helyek})",
                        [tuple(r[o] for o in oszlopok) for r in sorok])
        con.commit()

    f = {d: d_obj.forras for d, d_obj in dokok.items()}
    print(f"\n{len(sorok)} (cikk x ticker) sor. Osztályok forrásonként:")
    for k, v in sorted(Counter((f[r["doc_id"]], r["osztaly"]) for r in sorok).items()):
        print(f"  {k[0]:9} {k[1]:14} {v}")

    print("\nIndok (csak nem-BÉT):", dict(Counter(r["indok"] for r in sorok if r["indok"] != "bet")))
    print("Cikk-hű osztályok (osztaly_szoveg, nem-BÉT):",
          dict(Counter((f[r["doc_id"]], r["osztaly_szoveg"]) for r in sorok if r["indok"] != "bet")))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lepes_regi_hir()