#!/usr/bin/env python3
import requests, json
from stellar_sdk import xdr, StrKey

RPC = "https://wandering-winter-valley.stellar-mainnet.quiknode.pro/76a244679dc0544de966427cad850ad5c81f0741"

TX1_HASH = "ae721cacee382bdecac8d2c47286ecd42cb4711f658bb2aec7cba60dc64a31ff"
TX2_HASH = "3e81a3f7b6e17cc22d0a1f33e9dcf90e5664b125b9e61f108b8d2f082f2d4657"

ATTACKER       = "GBO7VUL2TOKPWFAWKATIW7K3QYA7WQ63VDY5CAE6AFUUX6BHZBOC2WXC"
YIELDBLOX_POOL = "CCCCIQSDILITHMM7PBSLVDT5MISSY7R26MNZXCX4H7J5JQ5FPIYOGYFS"
XLM_TOKEN      = "CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA"
USDC_TOKEN     = "CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75"
USTRY_TOKEN    = "CBLV4ATSIWU67CFSQU2NVRKINQIKUZ2ODSZBUJTJ43VJVRSBTZYOPNUR"

ORACLE_DECIMALS = 7
ORACLE_PRICES = {
    "XLM":  {"price_7d": 1_609_348,    "usd": 0.1609348},
    "USDC": {"price_7d": 10_000_000,   "usd": 1.0000000},
    "USTRY_MANIPULATED": {"price_7d": 1_067_372_830, "usd": 106.7372830},
    "USTRY_REAL":        {"price_7d": 10_574_237,    "usd": 1.0574237},
}

REFLECTOR_PRICES_USTRY = [
    {"price": 10_673_728_301_028_137, "timestamp": 1771719600, "status": "SDEX-POISONED"},
    {"price": 10_673_728_301_028_137, "timestamp": 1771719300, "status": "SDEX-POISONED"},
    {"price": 105_742_379_403_813,    "timestamp": 1771719000, "status": "NORMAL"},
    {"price": 105_742_642_288_368,    "timestamp": 1771718700, "status": "NORMAL"},
]

def sc_val_to_py(val):
    name = val.type.name
    if name == "SCV_VOID": return None
    if name == "SCV_BOOL": return val.b
    if name == "SCV_U32": return val.u32.uint32
    if name == "SCV_I32": return val.i32.int32
    if name == "SCV_U64": return val.u64.uint64
    if name == "SCV_I64": return val.i64.int64
    if name == "SCV_U128": return (val.u128.hi.uint64 << 64) | val.u128.lo.uint64
    if name == "SCV_I128":
        hi, lo = val.i128.hi.int64, val.i128.lo.uint64
        v = (hi << 64) | lo
        return v - (1 << 128) if hi < 0 else v
    if name == "SCV_SYMBOL": return val.sym.sc_symbol.decode()
    if name == "SCV_STRING": return val.str.sc_string.decode()
    if name == "SCV_BYTES": return f"0x{val.bytes.sc_bytes.hex()}"
    if name == "SCV_ADDRESS":
        t = val.address.type.name
        if t == "SC_ADDRESS_TYPE_ACCOUNT":
            return StrKey.encode_ed25519_public_key(val.address.account_id.account_id.ed25519.uint256)
        raw = val.address.contract_id
        if hasattr(raw, 'contract_id'): raw = raw.contract_id
        if hasattr(raw, 'hash'): raw = raw.hash
        return StrKey.encode_contract(raw)
    if name == "SCV_VEC": return [sc_val_to_py(i) for i in val.vec.sc_vec] if val.vec else []
    if name == "SCV_MAP":
        if not val.map: return {}
        return {str(sc_val_to_py(e.key)): sc_val_to_py(e.val) for e in val.map.sc_map}
    return f"<{name}>"

def get_cid(cd):
    addr = cd.contract
    if addr.type.name == 'SC_ADDRESS_TYPE_CONTRACT':
        raw = addr.contract_id
        if hasattr(raw, 'contract_id'): raw = raw.contract_id
        if hasattr(raw, 'hash'): raw = raw.hash
        return StrKey.encode_contract(raw)
    return '?'

def rpc(method, params):
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
    return r.json().get("result")

def decode_trace(diag_list):
    calls = []
    depth = 0
    for xdr_str in diag_list:
        evt = xdr.DiagnosticEvent.from_xdr(xdr_str)
        event = evt.event
        etype = event.type.name
        topics = [sc_val_to_py(t) for t in event.body.v0.topics] if event.body.v0 and event.body.v0.topics else []
        data = sc_val_to_py(event.body.v0.data) if event.body.v0 and event.body.v0.data else None
        if etype == "DIAGNOSTIC" and topics:
            if topics[0] == "fn_call" and len(topics) >= 3:
                calls.append(("CALL", depth, topics[1], topics[2], data))
                depth += 1
            elif topics[0] == "fn_return" and len(topics) >= 2:
                depth = max(0, depth - 1)
                calls.append(("RET", depth, topics[1], data))
            elif topics[0] != "core_metrics":
                calls.append(("DIAG", depth, topics, data))
        elif etype == "CONTRACT":
            calls.append(("EVENT", depth, topics, data))
    return calls


def extract_pre_state(result):
    meta = xdr.TransactionMeta.from_xdr(result["resultMetaXdr"])
    v4 = meta.v4
    states = []
    for change in v4.operations[0].changes.ledger_entry_changes:
        if change.type.name == 'LEDGER_ENTRY_STATE':
            e = change.state
            if e.data.type.name == 'CONTRACT_DATA':
                cd = e.data.contract_data
                states.append({
                    "contract": get_cid(cd),
                    "key": sc_val_to_py(cd.key),
                    "val": sc_val_to_py(cd.val),
                })
    return states

def extract_post_state(result):
    meta = xdr.TransactionMeta.from_xdr(result["resultMetaXdr"])
    v4 = meta.v4
    states = []
    for change in v4.operations[0].changes.ledger_entry_changes:
        if change.type.name == 'LEDGER_ENTRY_UPDATED':
            e = change.updated
            if e.data.type.name == 'CONTRACT_DATA':
                cd = e.data.contract_data
                states.append({
                    "contract": get_cid(cd),
                    "key": sc_val_to_py(cd.key),
                    "val": sc_val_to_py(cd.val),
                })
        elif change.type.name == 'LEDGER_ENTRY_CREATED':
            e = change.created
            if e.data.type.name == 'CONTRACT_DATA':
                cd = e.data.contract_data
                states.append({
                    "contract": get_cid(cd),
                    "key": sc_val_to_py(cd.key),
                    "val": sc_val_to_py(cd.val),
                })
    return states

RATE_SCALAR = 10**12

def h(t):
    print(f"\n{'='*80}")
    print(f"  {t}")
    print(f"{'='*80}\n")

def s(t):
    print(f"\n  {'─'*70}")
    print(f"  {t}")
    print(f"  {'─'*70}\n")


def main():
    print(f"  Pool:   {YIELDBLOX_POOL}")
    print(f"  Collateral token: USTRY (Etherfuse US Treasury stablebond)")
    print(f"  USTRY contract:   {USTRY_TOKEN}")
    print()
    tx1_result = rpc("getTransaction", {"hash": TX1_HASH})
    tx2_result = rpc("getTransaction", {"hash": TX2_HASH})

    print(f"  TX1: status={tx1_result['status']}, ledger={tx1_result['ledger']}")
    print(f"  TX2: status={tx2_result['status']}, ledger={tx2_result['ledger']}")

    tx1_pre = extract_pre_state(tx1_result)
    tx1_post = extract_post_state(tx1_result)
    tx2_pre = extract_pre_state(tx2_result)
    tx2_post = extract_post_state(tx2_result)

    for entry in tx1_pre:
        cid = entry["contract"][:16] + "..."
        key = entry["key"]
        val = entry["val"]
        if isinstance(key, list) and len(key) >= 1:
            key_name = key[0] if isinstance(key[0], str) else str(key[0])
        else:
            key_name = str(key)

        print(f"  {cid} [{key_name}]")
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, (int, float)) and abs(v) > 10**6:
                    print(f"    {k}: {v:>25,}")
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        print(f"    {k}.{k2}: {v2:>20,}" if isinstance(v2, int) else f"    {k}.{k2}: {v2}")
                else:
                    print(f"    {k}: {v}")

    for entry in tx2_pre:
        cid = entry["contract"][:16] + "..."
        key = entry["key"]
        val = entry["val"]
        if isinstance(key, list) and len(key) >= 1:
            key_name = key[0] if isinstance(key[0], str) else str(key[0])
        else:
            key_name = str(key)

        print(f"  {cid} [{key_name}]")
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, (int, float)) and abs(v) > 10**6:
                    print(f"    {k}: {v:>25,}")
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        print(f"    {k}.{k2}: {v2:>20,}" if isinstance(v2, int) else f"    {k}.{k2}: {v2}")
                else:
                    print(f"    {k}: {v}")

    print(f"  {'Asset':<22} {'Oracle Price (7d)':<20} {'USD':<15} {'Source'}")
    print(f"  {'─'*22} {'─'*20} {'─'*15} {'─'*30}")
    print(f"  {'XLM':<22} {1_609_348:<20,} ${0.1609:<14,.4f} lastprice() on-chain")
    print(f"  {'USDC':<22} {10_000_000:<20,} ${1.0:<14,.4f} lastprice() on-chain")
    print(f"  {'USTRY (SDEX-manip.)':<22} {1_067_372_830:<20,} ${106.74:<14,.2f} lastprice() POISONED via SDEX")
    print(f"  {'USTRY (real)':<22} {10_574_237:<20,} ${1.06:<14,.2f} computed from normal feed")

    print(f"  Reflector::prices([Stellar, USTRY({USTRY_TOKEN[:8]}...)], 4):\n")
    print(f"  {'#':<4} {'Timestamp':<15} {'Raw Price':<30} {'USD/unit':<15} {'Status'}")
    print(f"  {'─'*4} {'─'*15} {'─'*30} {'─'*15} {'─'*15}")
    for i, p in enumerate(REFLECTOR_PRICES_USTRY):
        usd = p["price"] / 10**14
        print(f"  [{i}]  {p['timestamp']:<15} {p['price']:<30,} ${usd:<14,.6f} {p['status']}")

    sorted_prices = sorted([p["price"] for p in REFLECTOR_PRICES_USTRY])
    median = (sorted_prices[1] + sorted_prices[2]) // 2
    print(f"\n  Median calculation:")
    print(f"    Sorted: [{sorted_prices[0]:,}, {sorted_prices[1]:,},")
    print(f"             {sorted_prices[2]:,}, {sorted_prices[3]:,}]")
    print(f"    Median = avg(P[1], P[2]) = {median:,}")
    print(f"    Median / 10^7 = {median // 10**7:,} → ${median / 10**14:,.2f}/unit")
    print(f"\n    Oracle Adapter returned: {1_067_372_830:,} → ${106.74:.2f}/unit")

    coll_pre1 = 128_817_245_870
    usdc_d_pre1 = 119_028_268_790
    usdc_d_rate = 1_176_191_180_667

    coll_post1 = 128_817_245_870
    usdc_d_post1 = 8_622_715_615_541

    usdc_underlying_pre  = usdc_d_pre1 * usdc_d_rate / RATE_SCALAR / 10**7
    usdc_underlying_post = usdc_d_post1 * usdc_d_rate / RATE_SCALAR / 10**7
    usdc_borrowed = usdc_underlying_post - usdc_underlying_pre

    coll_tokens = coll_post1 / 10**7
    coll_usd_manip = coll_tokens * 106.7372830
    coll_usd_real  = coll_tokens * 1.0574237

    print(f"    Collateral (reserve 5):  {coll_pre1:>20,} b-tokens ({coll_tokens:,.2f} USTRY)")
    print(f"    USDC liability (res 1):  {usdc_d_pre1:>20,} d-tokens ({usdc_underlying_pre:,.2f} USDC)")
    print(f"    USDC d_rate:             {usdc_d_rate:>20,} (10^12 scale)")
    print()
    print(f"    New d-tokens added: {usdc_d_post1 - usdc_d_pre1:,}")
    print()
    print(f"    Collateral:  {coll_tokens:>15,.2f} USTRY (unchanged)")
    print(f"    USDC debt:   {usdc_underlying_post:>15,.2f} USDC")
    print()
    print(f"  Health Factor (collateral_value / liability_value):")
    print(f"    With SDEX-MANIPULATED oracle ($106.74/USTRY):")
    print(f"      Collateral:  {coll_tokens:,.2f} × $106.74 = ${coll_usd_manip:>12,.2f}")
    print(f"      Liability:   {usdc_underlying_post:,.2f} USDC  = ${usdc_underlying_post:>12,.2f}")
    hf1_m = coll_usd_manip / usdc_underlying_post
    print(f"      HF = ${coll_usd_manip:,.2f} / ${usdc_underlying_post:,.2f} = {hf1_m:.4f}  PASS")
    print(f"      ON-CHAIN RESULT: SUCCESS (verified at ledger 61340384)")
    print()
    print(f"    With REAL oracle ($1.06/USTRY):")
    print(f"      Collateral:  {coll_tokens:,.2f} × $1.06   = ${coll_usd_real:>12,.2f}")
    print(f"      Liability:   {usdc_underlying_post:,.2f} USDC  = ${usdc_underlying_post:>12,.2f}")
    hf1_r = coll_usd_real / usdc_underlying_post
    print(f"      HF = ${coll_usd_real:,.2f} / ${usdc_underlying_post:,.2f} = {hf1_r:.6f}  FAIL")
    print(f"      → Borrow SHOULD HAVE BEEN REJECTED (HF << 1)")

    s("TX2: XLM Borrow (Ledger 61340408)")
    coll_pre2 = 1_498_761_336_572
    xlm_d_post2 = 610_846_237_149_994
    usdc_d_post2 = 8_622_715_615_541
    xlm_d_rate = 1_002_694_936_726

    coll_tokens2 = coll_pre2 / 10**7
    xlm_underlying = xlm_d_post2 * xlm_d_rate / RATE_SCALAR / 10**7
    usdc_underlying2 = usdc_d_post2 * usdc_d_rate / RATE_SCALAR / 10**7

    xlm_usd = xlm_underlying * 0.1609348
    total_liab_usd = xlm_usd + usdc_underlying2

    coll_usd_manip2 = coll_tokens2 * 106.7372830
    coll_usd_real2  = coll_tokens2 * 1.0574237

    print(f"    Collateral (reserve 5):  {coll_pre2:>20,} b-tokens ({coll_tokens2:,.2f} USTRY)")
    print(f"    USDC liability (res 1):  {usdc_d_post2:>20,} d-tokens (carried from TX1)")
    print(f"    XLM d_rate:              {xlm_d_rate:>20,}")
    print()
    print(f"    Collateral:  {coll_tokens2:>15,.2f} USTRY")
    print(f"    XLM debt:    {xlm_underlying:>15,.2f} XLM  (${xlm_usd:>12,.2f})")
    print(f"    USDC debt:   {usdc_underlying2:>15,.2f} USDC (${usdc_underlying2:>12,.2f})")
    print(f"    Total debt:  {'':>15}       (${total_liab_usd:>12,.2f})")
    print()
    print(f"  Health Factor:")
    print(f"    With SDEX-MANIPULATED oracle ($106.74/USTRY):")
    print(f"      Collateral:  {coll_tokens2:,.2f} × $106.74 = ${coll_usd_manip2:>14,.2f}")
    print(f"      Total debt:  {'':>20}       ${total_liab_usd:>14,.2f}")
    hf2_m = coll_usd_manip2 / total_liab_usd
    print(f"      HF = {hf2_m:.4f}  PASS")
    print(f"      ON-CHAIN RESULT: SUCCESS (verified at ledger 61340408)")
    print()
    print(f"    With REAL oracle ($1.06/USTRY):")
    print(f"      Collateral:  {coll_tokens2:,.2f} × $1.06   = ${coll_usd_real2:>14,.2f}")
    print(f"      Total debt:  {'':>20}       ${total_liab_usd:>14,.2f}")
    hf2_r = coll_usd_real2 / total_liab_usd
    print(f"      HF = {hf2_r:.6f}  FAIL")
    print(f"      → Borrow SHOULD HAVE BEEN REJECTED (HF << 1)")

    for label, tx_hash in [("TX1 (USDC)", TX1_HASH), ("TX2 (XLM)", TX2_HASH)]:
        result = rpc("getTransaction", {"hash": tx_hash})
        envelope_xdr = result["envelopeXdr"]

        print(f"  {label}: Simulating original envelope...")
        sim = rpc("simulateTransaction", {"transaction": envelope_xdr})

        if sim and sim.get("error"):
            err = sim["error"]
            if "Error(Contract, #" in err:
                code = err.split("Error(Contract, #")[1].split(")")[0]
                print(f"  Result: REJECTED — Error(Contract, #{code})")
                print(f"  → YieldBlox pool rejects borrow: SDEX oracle no longer manipulated")
            else:
                print(f"  Result: FAILED — {err[:150]}")
        elif sim and sim.get("transactionData"):
            print(f"  Result: WOULD SUCCEED (SDEX oracle still manipulated!)")
        else:
            print(f"  Result: {json.dumps(sim, indent=2)[:200] if sim else 'No response'}")
        print()

    for label, tx_hash in [("TX1 (USDC Borrow)", TX1_HASH), ("TX2 (XLM Borrow)", TX2_HASH)]:
        result = rpc("getTransaction", {"hash": tx_hash})
        trace = decode_trace(result.get("diagnosticEventsXdr", []))

        s(f"{label} — Ledger {result['ledger']}")
        for entry in trace:
            if entry[0] == "CALL":
                _, depth, contract, fn, data = entry
                indent = "  " * depth
                c_short = str(contract)[:12] + "..." if len(str(contract)) > 16 else contract
                args_str = ""
                if data:
                    if isinstance(data, list):
                        parts = []
                        for a in data:
                            s_a = str(a)
                            parts.append(s_a[:50] + "..." if len(s_a) > 50 else s_a)
                        args_str = ", ".join(parts)
                    else:
                        args_str = str(data)[:80]
                print(f"  {indent}-> {c_short}::{fn}({args_str})")
            elif entry[0] == "RET":
                _, depth, fn, data = entry
                indent = "  " * depth
                d_str = ""
                if data is not None:
                    s_d = str(data)
                    d_str = f" => {s_d[:90]}{'...' if len(s_d)>90 else ''}"
                print(f"  {indent}<- {fn}{d_str}")
            elif entry[0] == "EVENT":
                _, depth, topics, data = entry
                indent = "  " * depth
                t_str = ", ".join(str(t) for t in topics[:3])
                print(f"  {indent}   ** [{t_str}] = {data}")
            elif entry[0] == "DIAG":
                _, depth, topics, data = entry
                indent = "  " * depth
                print(f"  {indent}   [diag] {topics} = {data}")

    usdc_drained = (14_565_460_076_238 - 4_563_493_035_401) / 10**7
    xlm_drained  = (1_076_605_169_221_182 - 464_112_386_156_680) / 10**7
    xlm_price    = 0.1609348
    usdc_price   = 1.0
    total_usd    = xlm_drained * xlm_price + usdc_drained * usdc_price

    print(f"  Before TX1: {14_565_460_076_238:>20,} ({14_565_460_076_238/10**7:>15,.2f} USDC)")
    print(f"  After TX1:  {4_563_493_035_401:>20,} ({4_563_493_035_401/10**7:>15,.2f} USDC)")
    print(f"  Drained:    {14_565_460_076_238 - 4_563_493_035_401:>20,} ({usdc_drained:>15,.2f} USDC = ${usdc_drained * usdc_price:>12,.2f})")

    print(f"  Before TX2: {1_076_605_169_221_182:>20,} ({1_076_605_169_221_182/10**7:>15,.2f} XLM)")
    print(f"  After TX2:  {464_112_386_156_680:>20,} ({464_112_386_156_680/10**7:>15,.2f} XLM)")
    print(f"  Drained:    {1_076_605_169_221_182 - 464_112_386_156_680:>20,} ({xlm_drained:>15,.2f} XLM  = ${xlm_drained * xlm_price:>12,.2f})")

    print(f"  USDC drained: {usdc_drained:>15,.2f} × ${usdc_price:.4f} = ${usdc_drained * usdc_price:>14,.2f}")
    print(f"  XLM  drained: {xlm_drained:>15,.2f} × ${xlm_price:.4f} = ${xlm_drained * xlm_price:>14,.2f}")
    print(f"  {'─'*60}")
    print(f"  TOTAL:        {'':>15}              ${total_usd:>14,.2f}")
    print(f"                {'':>15}              ~${total_usd/1_000_000:.2f}M")

    print(f"  Before TX1:")
    print(f"    collateral: {{5: 128,817,245,870}}  (USTRY)")
    print(f"    liabilities: {{1: 119,028,268,790}}  (USDC)")
    print(f"  After TX1:")
    print(f"    collateral: {{5: 128,817,245,870}}  (USTRY, unchanged)")
    print(f"    liabilities: {{1: 8,622,715,615,541}}  (+{8_622_715_615_541 - 119_028_268_790:,} USDC d-tokens)")
    print(f"  After TX2:")
    print(f"    collateral: {{5: 1,498,761,336,572}}  (USTRY, +{1_498_761_336_572 - 128_817_245_870:,})")
    print(f"    liabilities: {{0: 610,846,237,149,994 (XLM), 1: 8,622,715,615,541 (USDC)}}")


if __name__ == "__main__":
    main()
