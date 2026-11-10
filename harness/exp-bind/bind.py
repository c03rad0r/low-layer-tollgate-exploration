#!/usr/bin/env python3
import json, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'harness'/'exp-c')); sys.path.insert(0,str(ROOT/'sidecar'))
import exp_c
from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.runner import DockerRunner

NODES={'a':'lt-bind-a','b':'lt-bind-b','c':'lt-bind-c'}

def sh(args,check=True):
    return subprocess.run(args,capture_output=True,text=True,check=check)

def status(container):
    return json.loads(sh(['docker','exec',container,'fipsctl','show','status']).stdout)

def send(sender,dest,token,payer):
    return sh(['docker','exec',NODES[sender],'python3','/bind/send_pay.py',dest,f'/bind/{token}',payer,'5'])

def main():
    for n in ('a','b','c'):
        exp_c.wait_for(lambda: sh(['docker','exec',NODES[n],'fipsctl','show','status'],False).returncode==0,25)
    st={n:status(NODES[n]) for n in NODES}; print('status:',json.dumps({n:st[n]['npub'] for n in NODES}))
    out=Path('/tmp/opencode/bind-out/server-output.json'); out.unlink(missing_ok=True)
    sh(['docker','exec','-d',NODES['b'],'python3','/bind/server.py','5'])
    time.sleep(1)
    dest=st['b']['ipv6_addr']
    # First the payer, then another peer replaying and then presenting it as its own.
    send('a',dest,'token1.txt',st['a']['npub'])
    time.sleep(0.3)
    send('c',dest,'token1.txt',st['a']['npub'])
    time.sleep(0.3)
    send('c',dest,'token1.txt',st['c']['npub'])
    time.sleep(0.3)
    send('a',dest,'token1.txt',st['a']['npub'])
    time.sleep(0.3)
    send('a',dest,'token2.txt',st['a']['npub'])
    for _ in range(60):
        if out.exists():
            try:
                data=json.loads(out.read_text())
                if len(data.get('events',[]))>=5: break
            except Exception: pass
        time.sleep(0.5)
    print(out.read_text())
    return 0

if __name__=='__main__':
    raise SystemExit(main())
