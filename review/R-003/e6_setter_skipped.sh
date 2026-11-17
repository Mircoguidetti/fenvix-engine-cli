#!/bin/bash
# E6: standalone `detpy repro` (what a developer runs) skips the state-setter search when the target
# already fails in the fixed order: repro.py `for pconf in passing or ([FIXED] if config != FIXED else [])`
# iterates over nothing. Needs the prepared idoft-py-autodoc checkout/venv from harness --mode prepare.
R=/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad/review-R-003
cd $R/work/src/idoft-py-autodoc; PY=$R/work/venvs/idoft-py-autodoc/bin/python
$PY -m detpy repro examples/test_pytest.py::test_post --seeds 20 --confirm 10 --out $R/e6.bundles -- -p no:cacheprovider -n 0 2>&1 | head -4
printf 'tests/test_not_generate.py::TestAutodocNotGenerate::test_should_not_generate\nexamples/test_pytest.py::test_post\n' > $R/e6_order.txt
echo "--- setter + target under --det (should pass if a setter exists):"
$PY -m pytest --det --det-order=$R/e6_order.txt -p no:cacheprovider -n 0 -q 2>&1 | tail -1
