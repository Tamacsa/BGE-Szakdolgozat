import közös as KÖ
import konfiguracio as K
import numpy as np

_MODELL = None

def _model():
    global _MODELL
    if _MODELL is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise SystemExit(
                "Hianyzik a sentence-transformers csomag. Telepitsd:\n"
                "    pip install sentence-transformers")
        print(f"Modell betoltese: {K.BEAGYAZO_MODELL} (elso alkalommal letolti) ...")
        _MODELL = SentenceTransformer(K.BEAGYAZO_MODELL)
    return _MODELL


def _bemenet(forras, cim, lead, szoveg) -> str | None:
    torzs = KÖ.bet_szoveg_tisztit(szoveg) if forras == "bet" else (szoveg or "")
    torzs = " ".join(torzs.split())[:K.BEAGYAZO_MAX_KAR]
    if len(torzs) < K.BEAGYAZO_MIN_KAR:
        return None
    if forras == "bet":
        cim = ""
    nyers = f"{cim or ''} {lead or ''} {torzs}"
    return K.BEAGYAZO_PREFIX + " ".join(nyers.split())

def _kodol(vek) -> bytes:
    return np.asarray(vek, dtype=np.float32).tobytes()


def beagyazo_lepes(kotegmeret:int=64):
    con = KÖ.db()
    sorok = con.execute("""
        SELECT d.doc_id, d.forras, d.cim, d.lead, d.szoveg
        FROM dokumentum d
        LEFT JOIN beagyazas b
          ON b.doc_id = d.doc_id AND b.modell = ?
        WHERE d.szoveg IS NOT NULL AND b.doc_id IS NULL
        ORDER BY d.doc_id
    """, (K.BEAGYAZO_MODELL,)).fetchall()

    if not sorok:
        print(f"Minden dokumentum be van agyazva ezzel a modellel: "
              f"{K.BEAGYAZO_MODELL}")
        return

    print(f"{len(sorok)} dokumentum beagyazasa ...")
    model = _model()
    bemenetek = []
    kihagyott = 0
    for r in sorok:
        b = _bemenet(r["forras"], r["cim"], r["lead"], r["szoveg"])
        if b is None:
            kihagyott += 1
        else:
            bemenetek.append((r["doc_id"], b))
    print(f"{len(bemenetek)} beagyazando, {kihagyott} kihagyva (tul rovid torzs).")
    CSOPORT = 256
    for i in range(0, len(bemenetek), CSOPORT):
        resz = bemenetek[i:i + CSOPORT]
        vek = model.encode([b for _, b in resz], batch_size=kotegmeret,
                           normalize_embeddings=True, show_progress_bar=False)
        con.executemany(
            "INSERT OR REPLACE INTO beagyazas (doc_id, modell, vek) VALUES (?,?,?)",
            [(d, K.BEAGYAZO_MODELL, _kodol(v)) for (d, _), v in zip(resz, vek)])
        con.commit()
        print(f"  {i + len(resz)}/{len(bemenetek)}")
    con.commit()

    ossz = con.execute("SELECT COUNT(*) FROM beagyazas WHERE modell=?",
                       (K.BEAGYAZO_MODELL,)).fetchone()[0]
    print(f"-> {len(sorok)} új vektor elmentve (osszesen {ossz} a tablaban).")
    print(f"-> {len(bemenetek)} új vektor elmentve (osszesen {ossz} a tablaban).")