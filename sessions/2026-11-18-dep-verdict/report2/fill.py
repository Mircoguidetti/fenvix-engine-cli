import re, subprocess, sys
R = "/home/user/fenvix-engine-cli"
B = "/tmp/claude-0/s/base2"
subprocess.run(["/tmp/claude-0/s/mkbase.sh"], check=True)
an = subprocess.run(["python3", f"{R}/harness/dep_verdict/analyze.py", "results/dv3", "results/local", "--commits", "commits.json"],
                    cwd=B, capture_output=True, text=True).stdout
rd = subprocess.run(["python3", f"{R}/sessions/2026-11-19-review-dep-verdict/rederive.py", B], capture_output=True, text=True).stdout
delta = subprocess.run(["python3", "/tmp/claude-0/s/delta.py", B], capture_output=True, text=True).stdout
cost = subprocess.run(["python3", "/tmp/claude-0/s/cost.py", B], capture_output=True, text=True).stdout
g = lambda pat, s=rd: re.search(pat, s).groups()
v = {}
v["D"], v["T"] = g(r"mean over pairs D ([\d.]+) T ([\d.]+)")
v["DR"], v["TR"] = g(r"mean of repo means D ([\d.]+) T ([\d.]+)")
v["DP"], v["TP"] = g(r"pooled D ([\d.]+) T ([\d.]+)")
v["NC"], v["DC"], _, v["NE"], v["DNE"], _ = g(r"env changed: n (\d+) D ([\d.]+) T ([\d.]+) \| unchanged: n (\d+) D ([\d.]+) T ([\d.]+)")
v["N50"], v["D50"], v["T50"] = g(r"cacheable>=50%: n (\d+) D ([\d.]+) T ([\d.]+)")
dc, dw, df, tc, tw = g(r"'D_checked': (\d+), 'D_wrong': (\d+), 'D_flaky': (\d+), 'T_checked': (\d+), 'T_wrong': (\d+)")
assert dw == "0" and df == "0" and tw == "0", (dw, df, tw)
v["VD"], v["VT"] = f"{int(dc):,}", f"{int(tc):,}"
v["R3"], = g(r"rule-of-three bound ([\d.]+)%")
v["NULLN"], nw, v["NULLP"] = g(r"null rule .*?: (\d+) reuses, (\d+) wrong \(([\d.]+)%\)")
v["NULLN"] = f"{int(v['NULLN']):,}"
inf, = g(r"could expose a wrong reuse\): (\d+)")
assert inf == "2" and nw == "2", (inf, nw)
v["BR"], = g(r"broken \(passed at P, not OK at C\): (\d+)")
pairs, = g(r"^pairs (\d+)", rd.replace("\n", "\n")) if False else re.search(r"\npairs (\d+) env-changed", rd).groups()
assert pairs == "130", pairs
v["TABLE"] = "\n".join(l for l in an.splitlines() if l.startswith("|")) + "\n\nFirst report on the same pairs (for comparison): esphome 82%, moto 76%, community.general 58%, integrations-core 37%, pydantic-ai 8%, transformers 1%, the other four 0%; 39.1% over pairs, 26.2% mean of repository means, 14.2% pooled; T 20.1% / 15.2% / 10.0%."
v["DELTA"] = "```\n" + delta.strip() + "\n```"
m = {l.split(" old")[0].strip(): re.search(r"new \(([\d.]+), ([\d.]+)\)", l).groups() for l in cost.splitlines() if "new (" in l}
v["KEYS"] = "%s / %s" % m["identity keys per test, mean per process (D0)"]
v["REC"] = "%s / %s s" % m["record s per process (D0)"]
v["CHK"] = "%s / %s s" % m["check s per process (D1)"]
for k in ("D", "T", "DR", "TR", "DP", "TP", "DC", "DNE", "D50", "T50"):
    v[k] = f"{float(v[k]):.1f}"
p = f"{R}/sessions/2026-11-18-dep-verdict/REPORT-2.md"
import os
os.makedirs(os.path.dirname(p), exist_ok=True)
s = open("/tmp/claude-0/s/REPORT-2.template.md").read()
for k, x in v.items():
    s = s.replace("{" + k + "}", str(x))
left = re.findall(r"\{[A-Z0-9]+\}", s)
assert not left, left
open(p, "w").write(s)
print({k: x for k, x in v.items() if k not in ("TABLE", "DELTA")})
print(rd)
