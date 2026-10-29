import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

import konfiguracio as K
import közös as KÖ
import portalok


def _uj_rekord(r, html: str) -> dict | None:

    szoveg, forras = portalok.kinyer_szoveg(html)
    if szoveg is None:
        return None

    fejlec = " ".join(filter(None, [r["cim"], r["lead"]]))
    teljes = " ".join(filter(None, [r["cim"], r["lead"], szoveg]))
    eros, gyenge = KÖ.tickerek(fejlec, teljes)
    return {
        "szoveg": szoveg,
        "szohossz": portalok._szohossz(szoveg),
        "szoveg_forras": forras,
        "norm_hash": KÖ.hash_szoveg(teljes),
        "ticker_eros": json.dumps(eros, ensure_ascii=False),
        "ticker_gyenge": json.dumps(gyenge, ensure_ascii=False),
    }


def ujratisztit(alkalmaz: bool = False):
    con = KÖ.db()
    sorok = con.execute(
        "SELECT doc_id, cim, lead, szoveg, szohossz, ticker_eros, ticker_gyenge, raw_path "
        "FROM dokumentum WHERE forras='portfolio' ORDER BY doc_id").fetchall()
    print(f"{len(sorok)} Portfolio-cikk, mód: "
          f"{'ÉLES ÁTÍRÁS' if alkalmaz else 'PRÓBA (nem ír)'}")


    valtozott: list[tuple[str, dict]] = []
    allapot = Counter()
    ticker_valtozas = 0
    szo_elotte = szo_utana = 0
    for i, r in enumerate(sorok, 1):
        p = K.BAZIS / r["raw_path"] if r["raw_path"] else None
        if p is None or not p.exists():
            allapot["nincs_nyers_fajl"] += 1
            continue
        uj = _uj_rekord(r, p.read_text(encoding="utf-8"))
        if uj is None:
            allapot["nincs_uj_szoveg"] += 1
            continue
        allapot[uj["szoveg_forras"]] += 1
        if uj["szoveg"] == r["szoveg"]:
            allapot["valtozatlan"] += 1
            continue
        valtozott.append((r["doc_id"], uj))
        szo_elotte += r["szohossz"] or 0
        szo_utana += uj["szohossz"]
        if (uj["ticker_eros"], uj["ticker_gyenge"]) != (r["ticker_eros"], r["ticker_gyenge"]):
            ticker_valtozas += 1
        if i % 200 == 0:
            print(f"  {i}/{len(sorok)} feldolgozva")

    print("\nAllapot:", dict(allapot))
    print(f"Megváltozó szöveg: {len(valtozott)} cikk")
    if valtozott:
        print(f"  átlagos szószám: {szo_elotte / len(valtozott):.0f} -> "
              f"{szo_utana / len(valtozott):.0f}")
        print(f"  ticker-lista változott: {ticker_valtozas} cikknél")
    if not alkalmaz:
        print("\nPRÓBA: nem történt írás. Éles futtatás: --alkalmaz")
        return

    con.commit()
    mentes = K.ADATBAZIS.with_name(
        f"korpusz.mentes_{datetime.now():%Y%m%d_%H%M%S}.sqlite")
    cel = sqlite3.connect(mentes)
    con.backup(cel)
    cel.close()
    print(f"\nMentés kész: {mentes.name}")

    try:
        for doc_id, uj in valtozott:
            con.execute(
                "UPDATE dokumentum SET szoveg=?, szohossz=?, szoveg_forras=?, "
                "norm_hash=?, ticker_eros=?, ticker_gyenge=? WHERE doc_id=?",
                (uj["szoveg"], uj["szohossz"], uj["szoveg_forras"],
                 uj["norm_hash"], uj["ticker_eros"], uj["ticker_gyenge"],
                 doc_id))
            con.execute("DELETE FROM beagyazas WHERE doc_id=?", (doc_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"{len(valtozott)} cikk átírva; a hozzájuk tartozó beágyazások törölve.")
    print("Következő lépés: beagyazas.beagyazo_lepes().")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="A már letöltött Portfolio-cikkek szövegének újratisztítása")
    ap.add_argument("--alkalmaz", action="store_true",
                    help="valóban átírja az adatbázist (alapból csak próba)")
    ujratisztit(alkalmaz=ap.parse_args().alkalmaz)
