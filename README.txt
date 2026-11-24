A BGE PSZK gazdaságinformatikus BA szakdolgozat elemzési kódja.
Téma: Redundáns hírek azonosítása és szűrése a magyar tőzsdei hírkereskedésben: költségoldali megközelítés

 
A hivatalos példány a szabályosan benyújtott PDF.
A kód leadáskori állapota: v1.0-leadas
 
 
1. MIT CSINÁL A KÓD?
 
A kód négy BÉT-papír híreit dolgozza fel, a 2024-01-02 és 2025-12-31 közötti időszakból, és három kérdésre válaszol:
 
  H1a             A portálhírek jelentős hányada régi hír-e?                        02_regi_hirek.ipynb
  H1b             A régi hírek percszintű abnormális ár- és forgalomhatása          01, 03, 04
                  kisebb-e, mint az újaké?
  Kutatási kérdés Többet ér-e a szövegalapú szűrés egy szöveget nem használó,       04_h1b_kutatási_kerdes_szakdolgozat.ipynb
                  triviális szabálynál?
 
A régi hír besorolása szótő-halmazok átfedésén alapul (Snowball magyar szótövező). Az eseménytanulmány perces rácson, abnormális hozammal és abnormális forgalommal méri a hatást. A módszertan és az eredmények a dolgozat 4–5. fejezetében találhatók.
 
 
2. A KÓDTÁR FELÉPÍTÉSE
 
projekt/
  01_arfolyam_szakdolgozat.ipynb               perces rács, abnormális hozam és forgalom
  02_regi_hirek.ipynb                          régi hírek besorolása, H1a, validáció
  02a_dokumentum_leiro.ipynb                   a korpusz leíró statisztikái
  03_esemenyek_szakdolgozat.ipynb              eseményablakok, kumulált mutatók
  04_h1b_kutatási_kerdes_szakdolgozat.ipynb    H1b, költségszámítás, kutatási kérdés
  bux_kosar.csv                                a BUX-kosár paraméterei (BÉT közlemények), elválasztó: ;
  requirements.txt
  közös.py, konfiguracio.py                    a notebookok által importált modulok
  bet_hirek.py, portalok.py, koteslista.py, hivatkozasok.py    adatgyűjtő modulok
  adat/                                        nem része a tárnak (lásd: 5. Adatok)
    korpusz.sqlite
    cache/                                     köztes és eredményfájlok

3. TELEPÍTÉS
 
Szükséges: Python 3.13 és a pip.
 
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
 
A notebookok közvetlenül használt csomagjai: numpy, pandas, matplotlib, scipy, snowballstemmer, openpyxl, pyarrow (a .parquet fájlokhoz), ipython, valamint a futtatáshoz jupyterlab vagy ipykernel. A pontos verziókat a requirements.txt rögzíti.

4. KONFIGURÁLÁS
 
A notebookok két környezeti változót olvasnak; ha nincsenek beállítva, a munkakönyvtár a projektmappa:
 
  PROJEKT_MAPPA   a projekt gyökérmappája                alapértelmezés: az aktuális munkakönyvtár
  CACHE_MAPPA     a köztes fájlok mappája                alapértelmezés: <PROJEKT_MAPPA>/adat/cache
 
  export PROJEKT_MAPPA=/utvonal/a/projekthez
  export CACHE_MAPPA=/utvonal/a/cache-hez      (elhagyható)
 
A notebookok az adatbázist csak olvasásra nyitják meg.
A paraméterek (ablakhossz, küszöbök, minta- és bootstrap-méret, véletlenmag) az egyes notebookok „Beállítások" szakaszában vannak, értelmezésükkel együtt. A véletlenszám-generátor magja mindenhol 42.

5. ADATOK
 
Az adatok nem részei a kódtárnak.
 
  adat/korpusz.sqlite   táblák: dokumentum, hivatkozas, kotes   (BÉT közleményei, Portfolio, Telex, a BÉT kötéslistája)
  bux_kosar.csv         a BUX-kosár paraméterei                 (BÉT indexkosár-közlemények)
 
Az adatbázis jogi okból nem közölhető, ezért a kód külső fél számára az adatok nélkül nem futtatható. Az adatok eredetét, gyűjtését és felhasználási feltételeit a dolgozat 4.3. és 4.11. pontja írja le.
 
6. FUTTATÁS


Futtatási sorrend (a .py fájlok mappájából):

  1. python -c "import portalok; portalok.lepes_felderites()"              Portfolio, Telex: cikk-URL-ek
  2. python -c "import portalok; portalok.lepes_letolt(portal='portfolio')"
     python -c "import portalok; portalok.lepes_letolt(portal='telex')"    cikkek letöltése
  3. python -c "import bet_hirek; bet_hirek.lepes_lista()"                 BÉT-közzétételek listája
  4. python -c "import bet_hirek; bet_hirek.lepes_letolt()"                BÉT-közzétételek letöltése
  5. python -c "import koteslista; koteslista.letolto_lepes()"             kötéslista
  6. python hivatkozasok.py                                                 hivatkozások kinyerése

Az eredmény az adat/korpusz.sqlite. A lépések megszakítás után folytathatók. A 6. lépés az 1-4. után fut.

A notebookokat ebben a sorrendben kell futtatni, mindegyiket frissen indított kernelből (Restart & Run All), a projektmappából indított Jupyterrel:

  1. 01_arfolyam_szakdolgozat
       bemenet: korpusz.sqlite (kotes), bux_kosar.csv
       kimenet (adat/cache/): perc_idosor.parquet
  2. 02_regi_hirek
       bemenet: korpusz.sqlite (dokumentum, hivatkozas), h1a_validacio.xlsx
       kimenet: regi_hir.parquet; h1a_validacio.xlsx, ha még nem létezik
  3. 02a_dokumentum_leiro
       bemenet: korpusz.sqlite (dokumentum)
       kimenet: nincs fájlkimenet (táblák, ábrák)
  4. 03_esemenyek_szakdolgozat
       bemenet: perc_idosor.parquet, regi_hir.parquet, korpusz.sqlite
       kimenet: esemeny.parquet
  5. 04_h1b_kutatási_kerdes_szakdolgozat
       bemenet: esemeny.parquet, regi_hir.parquet, perc_idosor.parquet, h1a_validacio.xlsx, korpusz.sqlite
       kimenet: 04_eredmenyek.xlsx



7. TESZTELÉS ÉS ELLENŐRZÉS
 
Automatizált (pytest) teszt jelenleg nincs.
 
Az eredmények ellenőrzése:
  - Restart & Run All a fenti sorrendben, tiszta virtuális környezetben; a notebookok kimenetének egyeznie kell a dolgozat táblázataival és ábráival.
  - A 01 notebook 3. szakasza a saját piaci súlyokat a BÉT által közölt kosársúlyokkal veti össze.
  - A 02 notebook 8. szakasza a besorolást a kézi címkékkel veti össze (egyezés, Cohen-kappa, szenzitivitás, specificitás).
  - A dolgozat 4.12. pontja (reprodukálhatóság) és 5.2. pontja (validáció) a módszert és az eredményt részletesen leírja.
 
 
8. KÜLSŐ KOMPONENSEK ÉS LICENC
 
A kód a fenti Python-csomagokat használja, mindegyik a saját licencével.
Az adatforrások felhasználási feltételeit a dolgozat 4.11. pontja tárgyalja.

 
9. MESTERSÉGES INTELLIGENCIA HASZNÁLATA
 
Az MI-használatot a dolgozat MI-használati nyilatkozata (G. melléklet) tartalmazza.

10. KAPCSOLAT
 
Tamás Attila Csaba