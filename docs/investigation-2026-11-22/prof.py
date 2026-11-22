# self time per bucket (engine module / deps / project / node internals / idle / gc) from a .cpuprofile
import json,sys,collections,re
p=json.load(open(sys.argv[1])); nodes={n["id"]:n for n in p["nodes"]}
dt=collections.Counter(); 
for i,s in enumerate(p["samples"]): dt[s]+=p["timeDeltas"][i]
def bucket(cf):
  u=cf.get("url",""); f=cf.get("functionName","")
  if f in("(idle)","(program)","(garbage collector)"): return f
  m=re.search(r"enginecopy/node/src/(.+?\.js)",u)
  if m: return "engine:"+m.group(1)
  if "/node_modules/" in u: return "deps:"+u.split("/node_modules/")[-1].split("/")[0]
  if u.startswith("node:"): return "node-internal"
  if u=="" : return "native/(no url)"
  return "project"
b=collections.Counter()
for nid,t in dt.items(): b[bucket(nodes[nid]["callFrame"])]+=t
tot=sum(b.values())
print("total %.2f s"%(tot/1e6))
for k,v in b.most_common(int(sys.argv[2]) if len(sys.argv)>2 else 25): print("%7.3f s %5.1f%%  %s"%(v/1e6,100*v/tot,k))
eng=sum(v for k,v in b.items() if k.startswith("engine:")); print("ENGINE TOTAL %.3f s"%(eng/1e6))
