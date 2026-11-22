import sys,collections,re
tot=0; selfb=collections.Counter(); incl=collections.Counter(); inclf=collections.Counter()
def b(fr):
  m=re.search(r"\((.*?):\d+\)",fr); f=m.group(1) if m else fr
  if "detpy/" in f: return "detpy:"+f.split("detpy/")[-1]
  if "/networkx/" in f and "site-packages" not in f: return "networkx(project)"
  if "_pytest" in f or "/pytest/" in f or "pluggy" in f: return "pytest"
  if "site-packages" in f: return "deps:"+f.split("site-packages/")[-1].split("/")[0]
  if ".so" in f or "lib" in f and "python3" not in f: return "native:"+f.split("/")[-1][:40]
  return "stdlib/other"
for line in open(sys.argv[1]):
  st,_,n=line.rstrip().rpartition(" ")
  try: n=int(n)
  except: continue
  fr=st.split(";"); tot+=n
  selfb[b(fr[-1])]+=n
  seen=set(b(x) for x in fr)
  for k in seen: incl[k]+=n
  sf=set()
  for x in fr:
    if "detpy/" in x:
      m=re.search(r"^(.*?) \(",x); sf.add((m.group(1) if m else x)+" @"+b(x))
  for k in sf: inclf[k]+=n
print("samples",tot)
print("-- self"); [print("%6.1f%% %s"%(100*v/tot,k)) for k,v in selfb.most_common(18)]
print("-- inclusive (any frame on stack)"); [print("%6.1f%% %s"%(100*v/tot,k)) for k,v in incl.most_common(18)]
print("-- inclusive detpy functions"); [print("%6.1f%% %s"%(100*v/tot,k)) for k,v in inclf.most_common(30)]
