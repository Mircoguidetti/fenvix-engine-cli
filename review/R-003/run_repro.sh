#!/bin/bash
# R-003 task 2: detpy repro (head 455c57c wheel) on 5 targets from 5 repositories; serial (-n 0), 20 seeds, 10 replays.
R=/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad/review-R-003
run() { repo=$1; tid=$2; tag=$3
  [ -s $R/repro/$tag.json ] && { echo "skip $tag"; return; }
  mkdir -p $R/repro
  cd $R/work/src/$repo || return
  t0=$(date +%s)
  nice -n 10 $R/work/venvs/$repo/bin/python -m detpy repro "$tid" --seeds 20 --confirm 10 --out $R/repro/$tag.bundles --json -- -p no:cacheprovider -n 0 > $R/repro/$tag.json.tmp 2> $R/repro/$tag.err
  echo "$tag exit=$? $(( $(date +%s) - t0 ))s"; mv $R/repro/$tag.json.tmp $R/repro/$tag.json
}
run idoft-ljson "test/test_ljson_disk.py::test_edit" ljson
run idoft-krllint "tests/test_open_task.py::OpenTaskTestCase::test_rule_with_fix" krllint
run idoft-accessify "tests/interfaces/test_implements.py::test_not_implements_private_access" accessify
run idoft-py-autodoc "examples/test_pytest.py::test_post" pyautodoc
run idoft-pykicad "tests/test_module.py::NetTests::test_net_auto_numbering" pykicad
echo ALLDONE
