#!/usr/bin/env python3
import argparse, json, sys, time
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,'/mint'); sys.path.insert(0,'/sidecar')
import verify_token
from gate_token import VerifiedJSON, proofs_from_result
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.vault import TokenVault
from tollgate_fips.payment import PaymentGate
from tollgate_fips.settlement import SettlementWorker
from settle_demo import LocalCashuRedeemer

p=argparse.ArgumentParser(); p.add_argument('phase',choices=['accept','settle']); p.add_argument('token'); p.add_argument('--keys-file',required=True); p.add_argument('--seller-pubkey',required=True); p.add_argument('--seller-nsec',default=''); p.add_argument('--mint',default='http://lt-mint:3338'); p.add_argument('--db-dir',required=True)
a=p.parse_args(); db=Path(a.db_dir); db.mkdir(parents=True,exist_ok=True)
token=Path(a.token).read_text().strip().splitlines()[0]
journal=NullifierJournal(str(db/'journal.sqlite3')); exposure=ExposureLedger(str(db/'exposure.sqlite3')); vault=TokenVault(str(db/'vault.sqlite3'))
cache=verify_token.fetch_keysets(a.mint,a.keys_file); verified=verify_token.verify(token,cache,a.seller_pubkey,a.mint,1)
proofs=proofs_from_result(verified,'npub1payer'); key=ExposureKey('npub1payer',verified['mint'],verified['unit'])
if a.phase=='accept':
    gate=PaymentGate(journal,exposure,VerifiedJSON(),'npub1testseller',cap_msat=100000)
    accepted=[]
    for proof in proofs:
        gate.accept(proof,'msg1-test',vault=vault,token=token)
        accepted.append(proof.nullifier[:20])
    out={'phase':'accept','offline':True,'amount_sat':verified['amount'],'proofs':len(proofs),'exposure_msat':str(exposure.outstanding(key)),'journal':[journal.state(p.mint_url,p.unit,p.keyset_id,p.nullifier) for p in proofs],'vault_pending':len(vault.pending()),'accepted_at':time.time()}
else:
    before=exposure.outstanding(key)
    worker=SettlementWorker(journal,exposure,LocalCashuRedeemer(a.mint,a.seller_nsec,str(db/'wallet')))
    result=worker.settle_vault(vault)
    gate=PaymentGate(journal,exposure,VerifiedJSON(),'npub1testseller',cap_msat=100000)
    replay=None
    try: gate.accept(proofs[0],'msg1-test')
    except Exception as exc: replay=type(exc).__name__
    out={'phase':'settle','exposure_before_msat':str(before),'exposure_after_msat':str(exposure.outstanding(key)),'settled':result.settled,'failed':result.failed,'redemptions':result.redemptions,'journal':[journal.state(p.mint_url,p.unit,p.keyset_id,p.nullifier) for p in proofs],'vault_pending':len(vault.pending()),'replay':replay,'settled_at':time.time()}
print(json.dumps(out,indent=2,default=str))
journal.close(); exposure.close(); vault.close()
