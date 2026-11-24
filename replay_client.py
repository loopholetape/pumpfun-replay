#!/usr/bin/env python3
"""replay_client.py: a small client for the replay for pump.fun bots at https://replay.loopholetape.com/.

It checks a picks document, replays its first pick for free, buys a full run and fetches a paid answer again. Only the
last two touch a wallet. Buying a run pays over x402 (version 2, "exact" on Solana): the service answers a request that
carries no payment with status 402 and its terms, this script signs one USDC transfer for exactly the price the terms
name, and sends the request again with that signed transfer in a header. The service that settles the payment pays the
network fee, so the wallet needs USDC and no SOL.

What this script does with your key: it reads the keypair file you name, signs that one transfer (or, for "results",
one line of text), and never writes the key anywhere or sends it to anyone. It talks to two addresses only: the replay
service and a Solana RPC node, which it asks for a recent blockhash. Read it before you give it a key, as you should
with any script that asks for one, and use a wallet that holds little.

  python replay_client.py check   picks.json
  python replay_client.py sample  picks.json
  python replay_client.py buy     picks.json --keypair ~/bot-wallet.json [--max-usdc 1] [--rpc URL] [--out answer.json]
  python replay_client.py results --keypair ~/bot-wallet.json

It needs Python 3.9 or newer and one package: pip install solders
"""
import argparse
import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request

SERVICE = 'https://replay.loopholetape.com/'
PAY_TO = '9HkwyUhDMyjbpSpnyu5xuZ9vRaFQeajnJsavhie7XcsT'          # the address the service is paid at; a run is never paid to another one unless you say so
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SOLANA_MAINNET = 'solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp'
RPC = 'https://api.mainnet-beta.solana.com'


def post(url, body, headers=None, timeout=120):
    req = urllib.request.Request(url, data=body, headers=dict({'Content-Type': 'application/json', 'User-Agent': 'replay-client/0.1'}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def header(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name), None)


def said(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def keypair(path):
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(json.load(open(os.path.expanduser(path)))))


def recent_blockhash(rpc):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'getLatestBlockhash', 'params': [{'commitment': 'confirmed'}]}).encode()
    st, _, raw = post(rpc, body, timeout=30)
    return json.loads(raw)['result']['value']['blockhash']


def signed_payment(kp, terms, accept, blockhash):
    """The header PAYMENT-SIGNATURE: one USDC transfer of exactly the named amount, signed by the wallet and left for the
    service's fee payer to sign and send."""
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import MessageV0, to_bytes_versioned
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import VersionedTransaction
    token = Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
    ata_program = Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
    budget = Pubkey.from_string('ComputeBudget111111111111111111111111111111')
    memo = Pubkey.from_string('MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr')
    mint, pay_to, fee_payer = Pubkey.from_string(accept['asset']), Pubkey.from_string(accept['payTo']), Pubkey.from_string(accept['extra']['feePayer'])
    payer = kp.pubkey()

    def account(owner):
        return Pubkey.find_program_address([bytes(owner), bytes(token), bytes(mint)], ata_program)[0]
    instructions = [
        Instruction(budget, bytes([2]) + struct.pack('<I', 20_000), []),
        Instruction(budget, bytes([3]) + struct.pack('<Q', 1), []),
        Instruction(token, bytes([12]) + struct.pack('<Q', int(accept['amount'])) + bytes([6]), [
            AccountMeta(account(payer), False, True), AccountMeta(mint, False, False),
            AccountMeta(account(pay_to), False, True), AccountMeta(payer, True, False)]),
        Instruction(memo, os.urandom(16).hex().encode(), []),
    ]
    message = MessageV0.try_compile(fee_payer, instructions, [], Hash.from_string(blockhash))
    signers = list(message.account_keys)[:message.header.num_required_signatures]
    if signers != [fee_payer, payer]:
        sys.exit('The transfer did not come out with the two signers it should have, so nothing was signed.')
    tx = VersionedTransaction.populate(message, [Signature.default(), kp.sign_message(to_bytes_versioned(message))])
    payload = {'x402Version': 2, 'resource': terms.get('resource'), 'accepted': accept, 'payload': {'transaction': base64.b64encode(bytes(tx)).decode()}}
    if terms.get('extensions'):
        payload['extensions'] = terms['extensions']
    return base64.b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()


def show(out):
    if out.get('explanation'):
        print(out['explanation'])
        print()
    for x in out.get('results') or []:
        paper = (x.get('paper') or {}).get('net_sol')
        print('%-24s %-22s replayed %s SOL%s' % (str(x.get('id'))[:24], x.get('status'), x.get('net_sol'), (' | on paper %s SOL' % paper[:14]) if paper else ''))
    for key in ('sample', 'kept', 'message'):
        if out.get(key):
            print(out[key])


def main():
    ap = argparse.ArgumentParser(description='Client for the replay for pump.fun bots.')
    ap.add_argument('command', choices=['check', 'sample', 'buy', 'results'])
    ap.add_argument('picks', nargs='?', help='the picks document, a JSON file')
    ap.add_argument('--keypair', help='the wallet that pays: a Solana keypair file (a JSON list of 64 numbers)')
    ap.add_argument('--max-usdc', type=float, default=1.0, help='never sign a payment above this (default 1)')
    ap.add_argument('--service', default=SERVICE)
    ap.add_argument('--pay-to', default=PAY_TO, help='the only address a payment may go to')
    ap.add_argument('--rpc', default=RPC, help='a Solana RPC node, asked for a recent blockhash and nothing else')
    ap.add_argument('--out', help='write the full answer to this file')
    a = ap.parse_args()
    base = a.service.rstrip('/') + '/'

    if a.command == 'results':
        if not a.keypair:
            sys.exit('results needs --keypair, the wallet that paid.')
        kp = keypair(a.keypair)
        line = 'replay results payer=%s date=%s' % (kp.pubkey(), time.strftime('%Y-%m-%d', time.gmtime()))
        st, _, raw = post(base + 'v1/replay/results', json.dumps({'payer': str(kp.pubkey()), 'signature': str(kp.sign_message(line.encode()))}).encode())
        out = said(raw)
        print('status %d: %s' % (st, out.get('message')))
        for i, run in enumerate(out.get('runs') or []):
            print('run %d, paid with transaction %s' % (i + 1, run.get('transaction')))
            show(run.get('answer') or {})
        if a.out:
            json.dump(out, open(a.out, 'w'), indent=1)
        return

    if not a.picks:
        sys.exit('%s needs a picks document.' % a.command)
    body = open(a.picks, 'rb').read()
    if a.command in ('check', 'sample'):
        st, _, raw = post(base + ('v1/check' if a.command == 'check' else 'v1/replay/first'), body)
        out = said(raw)
        print('status %d' % st)
        show(out)
        if a.out:
            json.dump(out, open(a.out, 'w'), indent=1)
        return

    if not a.keypair:
        sys.exit('buy needs --keypair, the wallet that pays.')
    url = base + 'v1/replay'
    st, headers, raw = post(url, body)
    if st != 402:
        print('The service did not ask for a payment (status %d), so nothing was signed.' % st)
        show(said(raw))
        return
    terms = json.loads(base64.b64decode(header(headers, 'payment-required')))
    accept = next((x for x in terms.get('accepts', []) if x.get('scheme') == 'exact' and x.get('network') == SOLANA_MAINNET and x.get('asset') == USDC), None)
    if accept is None:
        sys.exit('The terms offer no plain USDC payment on Solana, so nothing was signed.')
    price = int(accept['amount']) / 1e6
    print('The service asks for %.2f USDC, paid to %s.' % (price, accept['payTo']))
    if accept['payTo'] != a.pay_to:
        sys.exit('That is not the address this client pays (%s), so nothing was signed.' % a.pay_to)
    if price > a.max_usdc:
        sys.exit('That is more than --max-usdc allows (%.2f), so nothing was signed.' % a.max_usdc)
    kp = keypair(a.keypair)
    signature = signed_payment(kp, terms, accept, recent_blockhash(a.rpc))
    st, headers, raw = post(url, body, {'PAYMENT-SIGNATURE': signature})
    out = said(raw)
    receipt = header(headers, 'payment-response')
    receipt = json.loads(base64.b64decode(receipt)) if receipt else {}
    print('status %d' % st)
    if receipt.get('success'):
        print('The payment settled in transaction %s.' % receipt.get('transaction'))
    if st == 200:
        show(out)
    elif st == 402:
        print('The payment was not confirmed to this client. If the transfer left your wallet all the same, the answer is kept: wait a minute and run "results" with the same keypair.')
    else:
        show(out)
        print('Nothing was charged for this request.')
    if a.out and out:
        json.dump(out, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
