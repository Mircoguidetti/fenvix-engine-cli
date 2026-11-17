#!/bin/bash
# R-003 task 2: independent replay of each bundle and minimality check (target alone, same seed, must pass).
R=/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad/review-R-003
chk() { repo=$1; tag=$2; seed=$3
  cd $R/work/src/$repo; PY=$R/work/venvs/$repo/bin/python
  b=$(ls -d $R/repro/$tag.bundles/*/ | head -1)
  echo "== $tag replay:"; nice -n 10 $PY -m detpy replay $b 2>&1 | tail -2
  tail -1 $b/order.txt > $R/$tag.alone.txt
  sa=""; [ -n "$seed" ] && sa="--det-seed=$seed"
  for i in 1 2 3; do nice -n 10 $PY -m pytest --det $sa --det-order=$R/$tag.alone.txt -p no:cacheprovider -n 0 -q 2>&1 | grep -E "passed|failed|error" | tail -1; done
}
chk idoft-ljson ljson 1
chk idoft-krllint krllint 2
chk idoft-accessify accessify 5
chk idoft-pykicad pykicad 1
chk idoft-py-autodoc pyautodoc ""
