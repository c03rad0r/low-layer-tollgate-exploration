#!/usr/bin/env python3
import json, socket, subprocess, sys, time
from pathlib import Path

OUT=Path('/out/server-output.json')
count=int(sys.argv[1]) if len(sys.argv)>1 else 5
sock=socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('::',2122))
sock.settimeout(30)

def peers():
    data=json.loads(subprocess.check_output(['fipsctl','show','peers'],text=True))
    return {p['ipv6_addr']:p for p in data['peers']}

credits={}; used={}; events=[]; start=time.monotonic()
while len(events)<count and time.monotonic()-start<60:
    try:
        data,addr=sock.recvfrom(65535)
    except socket.timeout:
        break
    src=addr[0]
    peer=peers().get(src,{})
    npub=peer.get('npub','UNBOUND:'+src)
    try:
        msg=json.loads(data.decode())
    except Exception as exc:
        msg={}; err=str(exc)
    token=msg.get('token','')
    declared=msg.get('declared_payer')
    previous=used.get(token)
    if not token:
        action='NO_TOKEN'
    elif previous:
        action='REPLAY_REJECT'
    elif declared and declared!=npub:
        action='PAYER_MISMATCH_REJECT'
    else:
        used[token]=npub; credits[npub]=credits.get(npub,0)+msg.get('amount_sat',0)
        action='ACCEPT'
    events.append({'token_prefix':token[:12], 'declared_payer':declared,
                   'source_ipv6':src, 'bound_npub':npub, 'link_id':peer.get('link_id'),
                   'action':action,'credits_sat':dict(credits)})
    print(json.dumps(events[-1]),flush=True)
OUT.write_text(json.dumps({'events':events,'credits':credits,'used':used},indent=2))
