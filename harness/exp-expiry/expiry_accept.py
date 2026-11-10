#!/usr/bin/env python3
import argparse, asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0,'/mint'); sys.path.insert(0,'/sidecar')
import verify_token
from gate_token import VerifiedJSON, proofs_from_result
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.exposure import ExposureLedger
from tollgate_fips.payment import PaymentGate
from settle_demo import LocalCashuRedeemer

p=argparse.ArgumentParser(); p.add_argument('token'); p.add_argument('--keys-file',required=True); p.add_argument('--seller-pubkey',required=True); p.add_argument('--seller-nsec',default=''); p.add_argument('--window',type=int,default=3600); p.add_argument('--mint',default='http://lt-mint:3338'); p.add_argument('--redeem',action='store_true'); p.add_argument('--db-dir',required=True)
a=p.parse_args()
token=Path(a.token).read_text().strip().splitlines()[0]
cache=verify_token.fetch_keysets(a.mint,a.keys_file)
verified=verify_token.verify(token,cache,a.seller_pubkey,a.mint,1)
out={'window':a.window,'verify_ok':verified['ok'],'keyset_final_expiry':verified.get('keyset_final_expiry'),'checked_at':verified['checked_at']}
journal=NullifierJournal(a.db_dir+'/journal.sqlite3'); exposure=ExposureLedger(a.db_dir+'/exposure.sqlite3')
gate=PaymentGate(journal,exposure,VerifiedJSON(),'npub1testseller',cap_msat=100000,settlement_window_secs=a.window)
proofs=proofs_from_result(verified,'npub1payer'); out['proofs']=[{'amount_msat':str(p.amount_msat),'final_expiry':p.final_expiry} for p in proofs]
for proof in proofs:
    try:
        gate.accept(proof,'msg1-test',now=verified['checked_at'])
        out.setdefault('accepted',[]).append(True)
    except Exception as exc:
        out.setdefault('accepted',[]).append(type(exc).__name__+': '+str(exc))
if a.redeem:
    if a.seller_nsec=='': out['redeem']={'ok':False,'error':'missing nsec'}
    else:
        out['redeem']=LocalCashuRedeemer(a.mint,a.seller_nsec,a.db_dir+'/wallet').redeem(token)
    out['keysets_after_redeem']={}
journal.close(); exposure.close()
print(json.dumps(out,indent=2))
