# detpy Livello 0 — rapporto di misura (`mixed`)

Generato il 2026-11-16 14:51 UTC con detpy 0.1.0. Per repository: 10 run di baseline (ordine casuale con pytest-randomly, seme diverso per run, pytest-xdist `-n 2` dove la suite lo supporta) alternati a 10 run `--det` (ordine fisso, seriale); poi, per i test instabili in baseline, esplorazione con `--det-seed=1..20` e conferma 10/10 del seme che li fa fallire. 2 repository in parallelo su 4 CPU.

## Metrica principale

**Test instabili in baseline resi riproducibili: 0/0 = n/d** — esiste un `--det-seed` (o l'ordine fisso di `--det`) con cui il test fallisce 10 volte su 10, e almeno una configurazione `--det` in cui passa (altrimenti il fallimento è causato dal Livello 0 stesso, non riprodotto).

| pool | repository | test | instabili in baseline | riprodotti | % | mai falliti sotto --det | falliscono sempre sotto --det | falliscono a volte sotto --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Altre metriche

* rallentamento di `--det` (seriale) rispetto alla baseline (casuale, xdist dove possibile): mediana **n/d%** (min n/d%, max n/d%)
* precompilazione deterministica del bytecode, primo run `--det` di ogni repository: mediana **n/d s** (max n/d s); run successivi (verifica incrementale): mediana **n/d s**
* test instabili con `--det` (ordine fisso, 10 run): 0; resi stabili da `--det`: 0
* esito cambiato da `--det` (stabile in entrambe le modalità ma diverso): 0
* impronta identica in tutti i run `--det` (coperti dal Livello 0): 0 (n/d); non coperti: 0

## Per repository

| repo | pool | py | xdist | test | baseline s | det s | rall. % | precomp. 1° s | instabili | riprodotti | semi esplorati | cambiati da det | non coperti |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

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
