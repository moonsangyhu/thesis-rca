"""Deterministic, stdlib-only primary analysis; no input-reader is invoked here."""
from __future__ import annotations
import math, random
CONDITIONS=("runtime","length_placebo","blind_procedural_rag")
METHODOLOGY_DISPOSITION="CONFIRMATORY_WITH_DISCLOSED_NONINFORMATIVE_MACHINE_PARSE_DEVIATION"
def mcnemar_one_sided(b,c):
    return 1.0 if b+c==0 else sum(math.comb(b+c,k) for k in range(b,b+c+1))/2**(b+c)
def percentile(values,p):
    x=sorted(values); h=(len(x)-1)*p; j=int(h); return x[j]+(h-j)*(x[min(j+1,len(x)-1)]-x[j])
def paired_bootstrap(pairs,seed=20260831,reps=50000):
    if not pairs or reps <= 0: raise ValueError("invalid bootstrap input")
    rng=random.Random(seed); n=len(pairs); vals=[]
    for _ in range(reps):
        sample=[pairs[rng.randrange(n)] for _ in range(n)]
        vals.append(sum(rag-placebo for rag,placebo in sample)/n)
    return percentile(vals,.025),percentile(vals,.975)
def _binom_cdf(k,n,p): return sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(k+1))
def clopper_pearson(successes,total,alpha=.05):
    if total==0: return None
    def inverse_decreasing(target, k):
        lo,hi=0.,1.
        for _ in range(80):
            mid=(lo+hi)/2
            if _binom_cdf(k,total,mid)>target: lo=mid
            else: hi=mid
        return (lo+hi)/2
    lower=0. if successes==0 else inverse_decreasing(1-alpha/2,successes-1)
    upper=1. if successes==total else inverse_decreasing(alpha/2,successes)
    return lower,upper
def canonical_float(x):
    if not math.isfinite(x): raise ValueError("non-finite")
    return "0" if x==0 else format(x,".17g")
def validate_rows(rows):
    expected={(f"F{f}-t{t}",c) for f,t in ((1,2),(1,3),(2,1),(3,3),(3,4),(4,1),(5,2),(5,3),(6,5),(7,1),(7,3),(8,3)) for c in CONDITIONS}
    seen=[(r.get("incident_id"),r.get("condition")) for r in rows]
    if len(rows)!=36 or set(seen)!=expected or len(set(seen)) != len(seen): raise ValueError("INVALID_IDENTITY")
    if any(type(r.get("jlc_d")) is not bool for r in rows): raise ValueError("INVALID_SCORE")

def _incident_key(incident):
    fault, trial = incident.split("-t", 1)
    return int(fault[1:]), int(trial)
def primary(rows):
    # rows are synthetic/prevalidated score dicts, sorted by incident_id.
    validate_rows(rows); by={}
    for r in rows: by.setdefault(r["incident_id"],{})[r["condition"]]=r["jlc_d"]
    if any(set(v)!=set(CONDITIONS) for v in by.values()): raise ValueError("INVALID")
    pairs=[(int(v["blind_procedural_rag"]),int(v["length_placebo"])) for _,v in sorted(by.items(), key=lambda item: _incident_key(item[0]))]; b=sum(a and not z for a,z in pairs); c=sum(z and not a for a,z in pairs); rd=sum(a-z for a,z in pairs)/len(pairs); p=mcnemar_one_sided(b,c)
    status="REVERSED" if rd<0 else "NO_EVIDENCE" if rd==0 else "SUPPORTED" if p<.05 else "DIRECTIONAL_ONLY"
    cp=clopper_pearson(b,b+c)
    by_full = {}
    if all("full" in row for row in rows):
        if any(type(row["full"]) is not bool for row in rows): raise ValueError("INVALID_SCORE")
        for row in rows: by_full.setdefault(row["incident_id"], {})[row["condition"]] = row["full"]
        remediation_regression = sum(by_full[item]["blind_procedural_rag"] for item in by_full) < sum(by_full[item]["length_placebo"] for item in by_full)
    else:
        remediation_regression = False
    return {"b":b,"c":c,"rd":canonical_float(rd),"p":canonical_float(p),"discordance_ci":None if cp is None else [canonical_float(x) for x in cp],"rd_bootstrap_ci":[canonical_float(x) for x in paired_bootstrap(pairs)],"primary_status":status,"remediation_regression_flag":remediation_regression,"methodology_disposition":METHODOLOGY_DISPOSITION}
