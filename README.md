# YieldBlox-10M-PoC - SDEX Oracle Manipulation Exploit

**Date:** February 22, 2026 ~00:25 UTC

**Chain:** Stellar

**Protocol:** Blend V2 — YieldBlox DAO Pool

**Impact:** ~$10.86M drained (~61.25M XLM + ~1M USDC)

**Root cause:** SDEX price manipulation of an illiquid collateral asset (USTRY) feeding into the Reflector oracle


| Role | Address |
|------|---------|
| Attacker | `GBO7VUL2TOKPWFAWKATIW7K3QYA7WQ63VDY5CAE6AFUUX6BHZBOC2WXC` |
| YieldBlox DAO Pool (Blend V2) | `CCCCIQSDILITHMM7PBSLVDT5MISSY7R26MNZXCX4H7J5JQ5FPIYOGYFS` |
| Oracle Adapter | `CD74A3C54EKUVEGUC6WNTUPOTHB624WFKXN3IYTFJGX3EHXDXHCYMXXR` |
| Reflector Oracle | `CALI2BYU2JE6WVRUFYTS6MSBNEHGJ35P4AVCZYF3B6QOE3QKOB2PLE6M` |
| USTRY (collateral) | `CBLV4ATSIWU67CFSQU2NVRKINQIKUZ2ODSZBUJTJ43VJVRSBTZYOPNUR` |
| XLM (native) | `CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA` |
| USDC | `CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75` |

---

## Summary

An attacker manipulated the SDEX (Stellar Decentralized Exchange) price of **USTRY** (Etherfuse US Treasury stablebond) to inflate its valuation ~100x on the Reflector oracle, the USTRY/XLM order book had **<5 USTRY depth on the ask side**, making manipulation trivial, the attacker then used the inflated USTRY collateral valuation to borrow **~61.25M XLM** and **~1M USDC** from the community-ran YieldBlox DAO Pool on Blend V2.

---

## Attack Tx

| TX | Hash | Ledger | Action | Amount |
|----|------|--------|--------|--------|
| TX1 | [`ae721cac...`](https://stellar.expert/explorer/public/tx/ae721cacee382bdecac8d2c47286ecd42cb4711f658bb2aec7cba60dc64a31ff) | 61340384 | Borrow USDC | 1,000,196.70 USDC |
| TX2 | [`3e81a3f7...`](https://stellar.expert/explorer/public/tx/3e81a3f7b6e17cc22d0a1f33e9dcf90e5664b125b9e61f108b8d2f082f2d4657) | 61340408 | Borrow XLM | 61,249,278.31 XLM |

---

## Root cause

The USTRY token (Etherfuse US Treasury stablebond) had minimal liquidity on the Stellar DEX, the USTRY/XLM order book had **fewer than 5 USTRY** of depth on the ask side, making the SDEX price trivially manipulable with a small capital outlay.

The attacker placed trades on the SDEX to inflate the USTRY/XLM trading price by approximately **100x**, from ~$1.06 to ~$106.74 per USTRY.

// Reflector Oracle Poisoning

The [Reflector oracle](https://stellar.expert/explorer/public/contract/CALI2BYU2JE6WVRUFYTS6MSBNEHGJ35P4AVCZYF3B6QOE3QKOB2PLE6M) sources its price feeds from SDEX trading activity, when the attacker inflated the SDEX price, the Reflector oracle ingested the manipulated price.

**On-chain evidence** (from `diagnosticEventsXdr` of TX1)

```
Reflector::prices([Stellar, USTRY], 4) returned:

 #   Timestamp      Raw Price (14d)              USD/unit      Status
 [0] 1771719600     10,673,728,301,028,137       $106.737283   SDEX-POISONED
 [1] 1771719300     10,673,728,301,028,137       $106.737283   SDEX-POISONED
 [2] 1771719000        105,742,379,403,813       $1.057424     NORMAL
 [3] 1771718700        105,742,642,288,368       $1.057426     NORMAL
```

**2 out of 4 price entries** were poisoned with the inflated SDEX price, the Oracle Adapter (`CD74...MXXR`) returned the **latest price** rather than a robust aggregate, passing the full 100x inflation through to the Blend pool.

```
Oracle Adapter::lastprice(Stellar, USTRY) → {price: 1,067,372,830, timestamp: 1771719600}
                                              = $106.74/USTRY (should be ~$1.06)
```

// Health Factor Bypass

Blend V2 uses a health factor check to ensure borrowers maintain sufficient collateral, the health factor is computed as:

```
HF = collateral_value_USD / liability_value_USD
```

Where positions are converted from d-tokens/b-tokens to underlying using reserve rates (scalar = 10^12)

```
underlying = tokens × rate / 10^12
```

// USDC Borrow `Ledger 61340384`

Pre-TX1 state (from on-chain `resultMetaXdr`, `LEDGER_ENTRY_STATE`)

| Field | Value |
|-------|-------|
| Collateral (reserve 5, USTRY) | 128,817,245,870 b-tokens (12,881.72 USTRY) |
| USDC liability (reserve 1) | 119,028,268,790 d-tokens (~14,000 USDC) |
| USDC d_rate | 1,176,191,180,667 |

Post-TX1: USDC d-tokens grew to 8,622,715,615,541 (+8,503,687,346,751 from borrow).

Health factor with manipulated oracle **($106.74/USTRY)**

```
Collateral: 12,881.72 × $106.74 = $1,374,960.28
Liability:  1,014,196.21 USDC   = $1,014,196.21
HF = 1.3557 → PASS ✓ (pool accepts borrow)
```

<img width="1269" height="118" alt="image" src="https://github.com/user-attachments/assets/1df757d0-0354-405d-8f67-647547fd48ae" />

Health factor with real oracle **($1.06/USTRY):**

```
Collateral: 12,881.72 × $1.06 = $13,621.44
Liability:  1,014,196.21 USDC = $1,014,196.21
HF = 0.0134 → FAIL ✗ (borrow should be rejected)
```

<img width="1287" height="296" alt="image" src="https://github.com/user-attachments/assets/c3395a57-e4b8-47e3-ae8f-8e83215fcba7" />

// XLM Borrow `Ledger 61340408`

Pre-TX2 state (from on-chain `resultMetaXdr`)

| Field | Value |
|-------|-------|
| Collateral (reserve 5, USTRY) | 1,498,761,336,572 b-tokens (149,876.13 USTRY) |
| USDC liability (reserve 1) | 8,622,715,615,541 d-tokens (carried from TX1) |
| XLM d_rate | 1,002,694,936,726 |

Post-TX2: XLM d-tokens = 610,846,237,149,994 (new borrow).

**Health factor with manipulated oracle**

```
Collateral: 149,876.13 × $106.74 = $15,997,371.29
Total debt: $9,857,134.66 (XLM) + $1,014,196.21 (USDC) = $10,871,330.86
HF = 1.4715 → PASS ✓
```

<img width="1278" height="303" alt="image" src="https://github.com/user-attachments/assets/ba5b9a92-1707-4645-91ae-3849df6cee20" />

**Health factor with real oracle**

```
Collateral: 149,876.13 × $1.06 = $158,482.58
Total debt: $10,871,330.86
HF = 0.0146 → FAIL ✗
```

<img width="1298" height="467" alt="image" src="https://github.com/user-attachments/assets/f8f4fec9-656f-4d09-a9b8-57060d956df3" />

## Exec Traces

**TX1 call trace** (decoded from `diagnosticEventsXdr`)

```
→ BlendPool::submit(attacker, attacker, attacker, [{address: USDC, amount: 10001967040837, request_type: 4}])
  → OracleAdapter::decimals() → 7
  → OracleAdapter::lastprice(Stellar, USDC) → {price: 10000000}                    // $1.00 ✓
  → OracleAdapter::lastprice(Stellar, USTRY)
    → Reflector::prices([Stellar, USTRY], 4) → [POISONED, POISONED, normal, normal]
  ← lastprice → {price: 1067372830}                                                // $106.74 ✗
  → USDC::transfer(Pool → Attacker, 10001967040837)                                // 1,000,196.70 USDC
  ** [borrow, USDC, attacker] = [10001967040837, 8503687346751]
← submit → {collateral: {5: 128817245870}, liabilities: {1: 8622715615541}}
```

**TX2 call trace**

```
→ BlendPool::submit(attacker, attacker, attacker, [{address: XLM, amount: 612492783064502, request_type: 4}])
  → OracleAdapter::decimals() → 7
  → OracleAdapter::lastprice(Stellar, XLM) → {price: 1609348}                      // $0.16 ✓
  → OracleAdapter::lastprice(Stellar, USDC) → {price: 10000000}                    // $1.00 ✓
  → OracleAdapter::lastprice(Stellar, USTRY)
    → Reflector::prices([Stellar, USTRY], 4) → [POISONED, POISONED, normal, normal]
  ← lastprice → {price: 1067372830}                                                // $106.74 ✗
  → XLM::transfer(Pool → Attacker, 612492783064502)                                // 61,249,278.31 XLM
  ** [borrow, XLM, attacker] = [612492783064502, 610846237149994]
← submit → {collateral: {5: 1498761336572}, liabilities: {0: 610846237149994, 1: 8622715615541}}
```

---

// State Diff (Post Exploit)

| Asset | Before | After | Drained | USD Value |
|-------|--------|-------|---------|-----------|
| USDC | 1,456,546.01 | 456,349.30 | **1,000,196.70** | $1,000,196.70 |
| XLM | 107,660,516.92 | 46,411,238.62 | **61,249,278.31** | $9,857,140.35 |
| **Total** | | | | **$10,857,337.06** |

*USD values computed using on-chain oracle prices at time of exploit (XLM = $0.1609348, USDC = $1.00).*

### Attacker Flow

```
Before TX1:
  collateral:  {5: 128,817,245,870}          (12,881.72 USTRY)
  liabilities: {1: 119,028,268,790}          (~14,000 USDC)

After TX1 (USDC borrow):
  collateral:  {5: 128,817,245,870}          (unchanged)
  liabilities: {1: 8,622,715,615,541}        (+8,503,687,346,751 USDC d-tokens)

After TX2 (XLM borrow):
  collateral:  {5: 1,498,761,336,572}        (+1,369,944,090,702 USTRY b-tokens)
  liabilities: {0: 610,846,237,149,994,      (61.25M XLM)
                1: 8,622,715,615,541}         (1M USDC)
```

**Real value of attacker collateral:** ~$158,482 (149,876 USTRY at $1.06)

**Total borrowed value** ~$10,857,337

<img width="872" height="218" alt="image" src="https://github.com/user-attachments/assets/3ca97846-6587-4626-959f-e49db51c22ff" />

---

// Post-Exploit

| Action | Amount |
|--------|--------|
| USDC bridged to Ethereum mainnet | ~901,000 USDC |
| XLM distributed to 5+ secondary wallets | ~16,000,000 XLM |
| XLM frozen by Stellar network | ~48,000,000 XLM |

---

// Simulation Proof

Replaying the **exact same TX envelopes** via `simulateTransaction` against the current ledger state returns

```
TX1 (USDC): REJECTED — Error(Contract, #1206)
TX2 (XLM):  REJECTED — Error(Contract, #1206)
```

Error #1206 - **insufficient health factor**, the exploit is no longer reproducible because the SDEX oracle is no longer manipulated, this confirms the exploit was entirely dependent on the oracle price manipulation

Copyright (c) 2026, DK27ss, Pashov Audit Group
