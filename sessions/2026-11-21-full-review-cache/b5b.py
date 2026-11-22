import os, sys
sys.argv = sys.argv[:1]
exec(open("HERE/b5_entropy.py").read().split("PROBES = {")[0])
PROBES = {
 "numpy_default_rng": "import numpy as np\nv = np.random.default_rng().random()",
 "numpy_legacy_global": "import numpy as np\nv = np.random.random()",
 "numpy_RandomState_noseed": "import numpy as np\nv = np.random.RandomState().random_sample()",
 "numpy_SeedSequence": "import numpy as np\nv = np.random.SeedSequence().entropy",
}
src = open("HERE/b5_entropy.py").read()
exec(src[src.index("def runp"):])
