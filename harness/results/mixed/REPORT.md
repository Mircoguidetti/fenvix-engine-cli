# detpy Livello 0 — rapporto di misura (`mixed`)

Generato il 2026-11-16 14:51 UTC con detpy 0.1.0. Per repository: 10 run di baseline (ordine casuale con pytest-randomly, seme diverso per run, pytest-xdist `-n 2` dove la suite lo supporta) alternati a 10 run `--det` (ordine fisso, seriale); poi, per i test instabili in baseline, esplorazione con `--det-seed=1..20` e conferma 10/10 del seme che li fa fallire. 2 repository in parallelo su 4 CPU.

## Metrica principale

**Test instabili in baseline resi riproducibili: 74/75 = 98.7%** — esiste un `--det-seed` (o l'ordine fisso di `--det`) con cui il test fallisce 10 volte su 10, e almeno una configurazione `--det` in cui passa (altrimenti il fallimento è causato dal Livello 0 stesso, non riprodotto).

| pool | repository | test | instabili in baseline | riprodotti | % | mai falliti sotto --det | falliscono sempre sotto --det | falliscono a volte sotto --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dataset IDoFT | 1 | 218 | 75 | 74 | 98.7% | 0 | 1 | 0 |
| popolari | 1 | 5346 | 0 | 0 | n/d | 0 | 0 | 0 |
| totale | 2 | 5564 | 75 | 74 | 98.7% | 0 | 1 | 0 |

**(a) e (b) — semi esplorati prima di trovare il seme riproducente** (test riprodotti): 1: 5, 2-5: 69; mediana 3.

**(c) — primo evento divergente tra l'impronta di un run `--det` che passa e una che fallisce** (test riprodotti): `random` 74.

**Test instabili noti (IDoFT)**: 87 nei progetti misurati; presenti nella suite raccolta 87; instabili nella nostra baseline 74; riprodotti 74.

## Altre metriche

* rallentamento di `--det` (seriale) rispetto alla baseline (casuale, xdist dove possibile): mediana **38.3%** (min 35.1%, max 41.4%)
* precompilazione deterministica del bytecode, primo run `--det` di ogni repository: mediana **4.76 s** (max 7.38 s); run successivi (verifica incrementale): mediana **0.80 s**
* test instabili con `--det` (ordine fisso, 10 run): 0; resi stabili da `--det`: 75
* esito cambiato da `--det` (stabile in entrambe le modalità ma diverso): 0
* impronta identica in tutti i run `--det` (coperti dal Livello 0): 5564 (100.0%); non coperti: 0

## Per repository

| repo | pool | py | xdist | test | baseline s | det s | rall. % | precomp. 1° s | instabili | riprodotti | semi esplorati | cambiati da det | non coperti |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [pygments](https://github.com/pygments/pygments) | popular | 3.13 | sì | 5346 | 12.73 | 18.00 | 41.4 | 7.38 | 0 | 0 | 0 | 0 | 0 |
| [idoft-eppy](https://github.com/santoshphilip/eppy) | flaky | 3.9 | sì | 218 | 6.80 | 9.19 | 35.1 | 2.13 | 75 | 74 | 20 | 0 | 0 |

## Esempi

**idoft-eppy**

* `always-fails-under-det` — eppy/tests/test_parse_error.py::test_capture_real_error (fixed:10/10)
* `reproduced` — eppy/tests/test_IDF.py::TestIDF::test_popidfobject (seed 1): event #0: random.state @ <end> returned different values: "210d36883cd9b5fa29ba890844704072" vs "d22a73a5d1a1d35676f18cdbeafd6d1d"
* `reproduced` — eppy/tests/test_IDF.py::TestIDF::test_removeidfobject (seed 1): event #0: random.state @ <end> returned different values: "d4ce10b8dc41844dec3897a54dc42d38" vs "1cf410eb0945318d2b66d72e82b614ee"
* `reproduced` — eppy/tests/test_bunch_subclass.py::TestEpBunch::test_getreferingobjs (seed 2): event #0: random.state @ <end> returned different values: "4bea49645841669c8ee2099d6b2e472b" vs "b8401f6619fa1d5ece0cbc2fcabe40c5"

## Repository scartati

| repo | pool | motivo | dettaglio |
|---|---|---|---|
| idoft-reframe | flaky | install-failed | > import reframe.core.config as config File "/home/user/fenvix-engine-cli/.harness-work/src/idoft-reframe/reframe/core/config.py", line 10, in <module> import jsonschema ModuleNotFoundError: No module named 'jsonschema'  |

## Riproduzione

```bash
python harness/detpy_harness.py --set mixed --per-pool 25 --runs 10 --seeds 20 --confirm 10 --jobs 2 --checkpoint
```
Dettagli per test in `<repo>.csv`, per run in `<repo>_runs.csv`; colonne in `docs/HARNESS.md`.

## Note

* Il dataset FlaPy di Gruber et al. è pubblicato su Zenodo, non raggiungibile da questo ambiente (403 dal proxy di rete): il pool 'flaky' usa la sezione Python di IDoFT, con i progetti fissati al commit in cui i test instabili furono rilevati.
