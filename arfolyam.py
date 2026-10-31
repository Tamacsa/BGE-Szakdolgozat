import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import konfiguracio as K
import közös as KÖ

IZ = ZoneInfo("Europe/Budapest")
PERCEK = np.arange(K.PERC_KEZDET, K.PERC_VEG + 1)
N = len(PERCEK)


def betolt_kosar(con) -> int:
    con.execute("DELETE FROM bux_kosar")
    df = pd.read_csv(K.BUX_KOSAR_FAJL, sep=";")
    df.to_sql("bux_kosar", con, if_exists="append", index=False)
    return len(df)


def percrács(con):
    df = pd.read_sql("SELECT ticker, nap, ts_utc, ar, mennyiseg FROM kotes "
                     "ORDER BY ticker, nap, sorszam", con)
    helyi = pd.to_datetime(df.ts_utc, utc=True).dt.tz_convert(IZ)
    df["perc"] = (helyi.dt.hour * 60 + helyi.dt.minute).clip(K.PERC_KEZDET, K.PERC_VEG)
    df["ertek"] = df.ar * df.mennyiseg

    napok = sorted(df.nap.unique())
    idx = pd.MultiIndex.from_product([napok, PERCEK], names=["nap", "perc"])
    ki = {}

    for t, g in df.groupby("ticker"):
        a = g.groupby(["nap", "perc"]).agg(
            utolso=("ar", "last"), vol=("mennyiseg", "sum"),
            db=("ar", "size"), ertek=("ertek", "sum")
        ).reindex(idx)

        kitoltott = a.utolso.isna().to_numpy()
        ar = a.utolso.ffill().bfill()
        vwap = (a.ertek / a.vol.where(a.vol > 0)).to_numpy()
        shape = (len(napok), N)

        ki[t] = {
            "ar": ar.to_numpy().reshape(shape),
            "vwap": vwap.reshape(shape),
            "vol": a.vol.fillna(0).to_numpy().reshape(shape),
            "db": a.db.fillna(0).to_numpy().astype(int).reshape(shape),
            "kitoltott": kitoltott.reshape(shape),
        }
    return napok, ki


def suly_tabla(con, napok, rács):
    kosarak = pd.read_sql("SELECT ervenyes_tol, ticker, (q*ff*wf) as qfwf FROM bux_kosar", con)
    tolak = sorted(kosarak.ervenyes_tol.unique())
    tickerek = sorted(rács)

    sorok = []
    for d, nap in enumerate(napok):
        tol = max((t for t in tolak if t <= nap), default=None)
        if tol is None:
            raise SystemExit(f"{nap}: nincs érvényes indexkosár (a legkorábbi: {tolak[0]})")

        kosar_szelet = kosarak[kosarak.ervenyes_tol == tol].set_index("ticker")["qfwf"]

        for t in tickerek:
            zaras = rács[t]["ar"][d - 1, -1] if d > 0 else rács[t]["ar"][0, 0]
            ertek = kosar_szelet.get(t, 0) * float(zaras)
            sorok.append((nap, t, tol, float(zaras), ertek))

    s = pd.DataFrame(sorok, columns=["nap", "ticker", "kosar_tol", "elozo_zaras", "ertek"])
    s["suly"] = s.ertek / s.groupby("nap").ertek.transform("sum")
    return s


def szamol(con):
    napok, rács = percrács(con)
    D = len(napok)
    tickerek = sorted(rács)
    suly = suly_tabla(con, napok, rács)
    W = {t: suly[suly.ticker == t].suly.to_numpy() for t in tickerek}

    R = {}
    for t in tickerek:
        folyamatos = np.log(rács[t]["ar"].reshape(-1))
        R[t] = np.diff(folyamatos, prepend=np.nan).reshape(D, N)

    percek_utc = (pd.to_datetime(np.repeat(napok, N)) +
                  pd.to_timedelta(np.tile(PERCEK, D), unit="m")
                  ).tz_localize(IZ).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:00Z")

    tablak = []
    for t in tickerek:

        masik = [k for k in tickerek if k != t]
        szamlalo = sum(W[k][:, None] * R[k] for k in masik)
        nevezo = sum(W[k] for k in masik)[:, None]
        piaci = szamlalo / nevezo
        ar = R[t] - piaci

        V = rács[t]["vol"]
        M = pd.DataFrame(V).shift(1).rolling(window=K.AV_NAPOK, min_periods=K.AV_NAPOK).mean().to_numpy()
        av = np.log((V + 1) / (M + 1))

        tablak.append(pd.DataFrame({
            "ticker": t, "nap": np.repeat(napok, N), "perc": np.tile(PERCEK, D),
            "ts_utc": percek_utc,
            "ar_utolso": rács[t]["ar"].reshape(-1), "ar_vwap": rács[t]["vwap"].reshape(-1),
            "mennyiseg": V.reshape(-1), "kotes_db": rács[t]["db"].reshape(-1),
            "kitoltott": rács[t]["kitoltott"].reshape(-1).astype(int),
            "hozam": R[t].reshape(-1), "piaci_hozam": piaci.reshape(-1),
            "ar": ar.reshape(-1), "av_atlag": M.reshape(-1), "av": av.reshape(-1)}))

    return suly, pd.concat(tablak, ignore_index=True)


def ellenorzes(con, suly, id_sor):
    print("\nSúlyellenőrzés a hivatkozási napon (BÉT közölt súly vs. számolt, 4 papírra normálva):")
    zaras = (id_sor[id_sor.perc == K.PERC_VEG].set_index(["nap", "ticker"]).ar_utolso)
    for r in con.execute("SELECT DISTINCT ervenyes_tol, hivatkozasi_nap FROM bux_kosar "
                         "ORDER BY 1").fetchall():
        nap = r["hivatkozasi_nap"]
        if (nap, "OTP") not in zaras.index:
            print(f"  {nap}: nincs ilyen nap az adatban, kihagyva")
            continue
        sorok = con.execute("SELECT ticker, q*ff*wf AS e, suly_kosarban_pct AS p FROM bux_kosar "
                            "WHERE ervenyes_tol=?", (r["ervenyes_tol"],)).fetchall()
        ert = {s["ticker"]: s["e"] * zaras[(nap, s["ticker"])] for s in sorok}
        ossz, kozolt = sum(ert.values()), sum(s["p"] for s in sorok)
        reszek = []
        for s in sorok:
            sz, kz = ert[s["ticker"]] / ossz * 100, s["p"] / kozolt * 100
            reszek.append(f"{s['ticker']} {sz:5.2f}% (BÉT {kz:5.2f}%)")
        print(f"  {nap}: " + " | ".join(reszek))


def lepes_arfolyam():
    con = KÖ.db()
    print(f"{betolt_kosar(con)} sor a bux_kosar táblába ({K.BUX_KOSAR_FAJL.name})")
    suly, id_sor = szamol(con)
    con.execute("DELETE FROM piaci_suly")
    con.execute("DELETE FROM perc_idosor")
    suly.to_sql("piaci_suly", con, if_exists="append", index=False)
    id_sor.to_sql("perc_idosor", con, if_exists="append", index=False, chunksize=100_000)
    con.commit()

    print(f"\nperc_idosor: {len(id_sor):,} sor ({id_sor.nap.nunique()} nap x {N} perc x "
          f"{id_sor.ticker.nunique()} papír)")
    print("\nPapíronként (hozam, AR bázispontban; AV logaritmikus):")
    for t, g in id_sor.groupby("ticker"):
        print(f"  {t:9} kitöltött perc {g.kitoltott.mean():5.1%} | "
              f"hozam sd {g.hozam.std() * 1e4:5.2f} bp | AR sd {g.ar.std() * 1e4:5.2f} bp, "
              f"átlag {g.ar.mean() * 1e4:+.3f} bp | corr(hozam, proxy) "
              f"{g.hozam.corr(g.piaci_hozam):5.3f} | AV átlag {g.av.mean():+.3f}, sd {g.av.std():.3f}")
    ures = id_sor[["hozam", "piaci_hozam", "ar", "av"]].isna().sum().to_dict()
    print("\nÜres (NaN) értékek:", ures)
    ellenorzes(con, suly, id_sor)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lepes_arfolyam()