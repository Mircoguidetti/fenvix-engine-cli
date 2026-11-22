# run a command; timestamp the first output line matching each marker; print JSON
import subprocess,sys,time,json,re,os
label=sys.argv[1]; cwd=sys.argv[2]; cmd=sys.argv[3:]
env={k:v for k,v in os.environ.items() if k not in("CI","GITHUB_ACTIONS","NODE_OPTIONS")}
M={"detjs_banner":r"^detjs 0\.1\.0","RUN":r"RUN +v","Test Files":r"Test Files","Duration":r"Duration ","serial_run":r"detjs: serial run","trace":r"detjs: trace"}
t0=time.time(); p=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors="replace")
seen={}; dur=None; ru=os.times()
for line in p.stdout:
  for k,r in M.items():
    if k not in seen and re.search(r,line): seen[k]=round(time.time()-t0,3)
  if "Duration" in line and dur is None: dur=line.strip()
p.wait(); wall=round(time.time()-t0,3); r1=os.times()
print(json.dumps({"label":label,"wall":wall,"cpu_children_s":round((r1.children_user-ru.children_user)+(r1.children_system-ru.children_system),2),"marks":seen,"vitest":dur,"exit":p.returncode}))
