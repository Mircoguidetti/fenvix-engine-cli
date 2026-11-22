import json,sys,collections
j=json.load(open(sys.argv[1]))
print("summary",json.dumps(j["summary"]))
groups=collections.defaultdict(list)
for x in j["tests"]:
  if x["status"]=="stable": continue
  d=x.get("divergence") or {}
  ea=d.get("event_a") or {}
  key=(x["status"],d.get("reason"),ea.get("o"),(ea.get("at") or "")[:70])
  groups[key].append((x,d))
for k,v in sorted(groups.items(),key=lambda kv:-len(kv[1])):
  x,d=v[0]
  print(f"\n[{len(v)}] status={k[0]} reason={k[1]} op={k[2]} at={k[3]}")
  print("   e.g.", x["nodeid"][:150])
  print("   A:", json.dumps(d.get("event_a"))[:220]); print("   B:", json.dumps(d.get("event_b"))[:220])
  print("   ", (d.get("description") or "")[:300])
