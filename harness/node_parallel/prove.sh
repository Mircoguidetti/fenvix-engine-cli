#!/usr/bin/env bash
# Serial vs parallel, same outcome and same fingerprint (row JS-07).
#
# For one installed project and runner: run the suite with one lane and with N lanes, then ask the verifier
# (crates/detpy-core/src/verify.rs, through `fenvix verify`) whether the two runs are IDENTICAL. The run is the
# product claim: parallel must observe exactly what serial observed. Anything but IDENTICAL exits non-zero, so a
# divergence fails the job rather than being reported as a note.
#
#   prove.sh <project-dir> <runner> <lanes> <out-dir> [runner args...]
#
# Labels: MEASURED (a run here). Nothing in this script estimates.
set -uo pipefail
d="$1"; runner="$2"; lanes="$3"; out="$4"; shift 4
mkdir -p "$out"
name="$(basename "$d")"
ser="$out/$name-$runner-serial.jsonl"
par="$out/$name-$runner-par$lanes.jsonl"
cd "$d" || { echo "prove: no such directory: $d" >&2; exit 2; }

echo "== $name / $runner: one lane =="
rm -rf .detjs
timeout 3600 fenvix node "$runner" --det --det-workers=1 --det-trace="$ser" "$@" >"$out/$name-$runner-serial.log" 2>&1
rc_ser=$?
echo "== $name / $runner: $lanes lanes =="
rm -rf .detjs
timeout 3600 fenvix node "$runner" --det --det-workers="$lanes" --det-trace="$par" "$@" >"$out/$name-$runner-par.log" 2>&1
rc_par=$?

echo "serial rc=$rc_ser  parallel rc=$rc_par"
if [ "$rc_ser" != "$rc_par" ]; then
  echo "BLOCKER: $name/$runner exit status differs between serial ($rc_ser) and parallel ($rc_par)" >&2
  exit 1
fi
for t in "$ser" "$par"; do
  [ -s "$t" ] || { echo "BLOCKER: $name/$runner produced no trace at $t" >&2; exit 1; }
done

echo "== $name / $runner: verify serial vs $lanes lanes =="
vout="$out/$name-$runner-verify.txt"
fenvix verify "$ser" "$par" >"$vout" 2>&1
vrc=$?
cat "$vout"
if ! grep -q "^verdict: IDENTICAL" "$vout"; then
  echo "BLOCKER: $name/$runner serial and parallel are not IDENTICAL (fenvix verify exit $vrc)" >&2
  exit 1
fi
echo "OK: $name/$runner parallel ($lanes lanes) is IDENTICAL to serial (MEASURED)"
