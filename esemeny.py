import sys
from bisect import bisect_left
from collections import Counter

import numpy as np
import pandas as pd

import konfiguracio as K
import közös as KÖ
from arfolyam import IZ, N

KEZDETI = 30 #Roland Gillet és Thomas Renault: When Machines Read the Web: Market Efficiency and Costly Information Acquisition at the Intraday Level. Finance, 40(2), 7–49, 2019. DOI: 10.3917/fina.402.0007.


KESLELTETETT = 60 #Jan Muntermann és André Güttler: Intraday Stock Price Effects of Ad Hoc Disclosures: The German Case. Goethe-Universität Frankfurt am Main, Working Paper Series: Finance & Accounting, No. 145, 2005. február, mivel itt már nem mutat szignifikáns növekedést


def _tombok(con):
    d = pd.read_sql("SELECT ticker, nap, ar, av, av_atlag, mennyiseg FROM perc_idosor "
                    "ORDER BY ticker, nap, perc", con)
    napok = sorted(d.nap.unique())
    D = len(napok)
    ki = {}
    for t, g in d.groupby("ticker"):
        ki[t] = {c: g[c].to_numpy().reshape(D, N) for c in ("ar", "av", "av_atlag", "mennyiseg")}
    return napok, ki


def _figyelem(V: np.ndarray) -> np.ndarray:
    vol = pd.Series(V.sum(axis=1))
#craig mkcinlay (1997)vagy Li  Luan
    ki = np.log(vol.shift(1) / vol.shift(1).rolling(window=20).mean())
    return ki.to_numpy()


def _cav(a, d, szelet) -> float:
    megfigyelt = a["mennyiseg"][d, szelet].sum()
    reference = a["av_atlag"][d, szelet].sum()
    return float(np.log((megfigyelt + 1) / (reference + 1)))


def epit(con):
    napok, T = _tombok(con)
    D = len(napok)
    figyelem = {t: _figyelem(a["mennyiseg"]) for t, a in T.items()}

    sorok = pd.read_sql(
        "SELECT r.doc_id, r.ticker, d.forras, r.osztaly, r.osztaly_szoveg, d.megjelenes_utc "
        "FROM regi_hir r JOIN dokumentum d USING(doc_id) "
        "WHERE r.osztaly != 'rovid' ORDER BY d.megjelenes_utc", con)

    helyi = pd.to_datetime(sorok.megjelenes_utc, utc=True).dt.tz_convert(IZ)
    sorok["nap"] = helyi.dt.strftime("%Y-%m-%d")
    sorok["perc"] = helyi.dt.hour * 60 + helyi.dt.minute

    ki, eldobva = [], Counter()

    for r in sorok.itertuples(index=False):
        di = bisect_left(napok, r.nap)
        kereskedesi_nap = (di < D and napok[di] == r.nap)

        if kereskedesi_nap and K.PERC_KEZDET <= r.perc <= K.PERC_VEG:
            tipus, d, s0 = "nyitvatartas", di, r.perc + 1
        elif kereskedesi_nap and r.perc < K.PERC_KEZDET:
            tipus, d, s0 = "nyitas_elott", di, K.PERC_KEZDET
        elif kereskedesi_nap:
            tipus, d, s0 = "zaras_utan", di + 1, K.PERC_KEZDET
        else:
            tipus, d, s0 = "szunnap", di, K.PERC_KEZDET

        if d >= D:
            eldobva["nincs_kovetkezo_nap"] += 1
            continue

        i0 = s0 - K.PERC_KEZDET
        if i0 + KEZDETI > N:
            eldobva["kezdeti_ablak_nem_fer_bele"] += 1
            continue

        a = T[r.ticker]
        k = slice(i0, i0 + KEZDETI)
        v = slice(i0 + KEZDETI, min(i0 + KEZDETI + KESLELTETETT, N))
        kesl = a["ar"][d, v]

        ki.append((r.doc_id, r.ticker, r.forras, r.osztaly, r.osztaly_szoveg,
                   r.megjelenes_utc, tipus, napok[d], s0,
                   a["ar"][d, k].sum(), kesl.sum() if len(kesl) else np.nan,
                   _cav(a, d, k), len(kesl), figyelem[r.ticker][d]))

    cols = ["doc_id", "ticker", "forras", "osztaly", "osztaly_szoveg", "t0_utc", "t0_tipus",
            "nap", "kezdo_perc", "car_kezdeti", "car_kesleltetett", "cav_kezdeti",
            "kesl_percek", "figyelem"]
    return pd.DataFrame(ki, columns=cols), eldobva


def lepes_esemeny():
    con = KÖ.db()
    df, eldobva = epit(con)
    con.execute("DELETE FROM esemeny")
    df.to_sql("esemeny", con, if_exists="append", index=False)
    con.commit()
    print(f"{len(df)} esemény elmentve; eldobva: {dict(eldobva)}")
    print("\nOsztály x forrás:")
    print(df.groupby(["forras", "osztaly"]).size().unstack(fill_value=0).to_string())
    print("\nt0 típusa:")
    print(df.groupby(["t0_tipus", "osztaly"]).size().unstack(fill_value=0).to_string())
    print(f"\nTeljes (90 perces) késleltetett ablak: {(df.kesl_percek == KESLELTETETT).mean():.1%}"
          f" | van figyelem-érték: {df.figyelem.notna().mean():.1%}"
          f" | van CAV: {df.cav_kezdeti.notna().mean():.1%}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lepes_esemeny()