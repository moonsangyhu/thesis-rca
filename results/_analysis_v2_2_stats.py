import csv, collections, json, math, random
import numpy as np
from scipy import stats

random.seed(42); np.random.seed(42)
rows = list(csv.DictReader(open('results/experiment_results_v2_2.csv')))
ARMS = ['C1_A','C2_gitops','C3_rag','C4_both','C5_placebo']
FAULTS = [f'F{i}' for i in range(1,13)]

# index: (fault,trial,arm) -> row
idx = {(r['fault_id'],r['trial'],r['arm']): r for r in rows}

def correct(r, thr):
    return 1 if float(r['rep_correctness_score']) >= thr else 0

def arm_acc(arm, thr):
    c = sum(correct(idx[(f,t,arm)], thr) for f in FAULTS for t in ['1','2','3','4','5'])
    return c, c/60

print("="*70); print("ARM ACCURACY @ thresholds")
for thr in [0.5,0.6,0.7]:
    print(f"\n--- thr={thr} ---")
    for arm in ARMS:
        c,a = arm_acc(arm,thr); print(f"  {arm:12s} {c:2d}/60 = {a*100:5.1f}%")

# ---- Newcombe hybrid score CI for paired difference (MOVER-Wilson) ----
def wilson(k,n,z=1.96):
    if n==0: return (0,0)
    p=k/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return (c-h, c+h)

def newcombe_paired(arm1, arm2, thr, z=1.96):
    # paired by (fault,trial). build 2x2
    n=60
    a=b=c=d=0  # a both correct, b a1c a2w, c a1w a2c, d both wrong
    for f in FAULTS:
        for t in ['1','2','3','4','5']:
            x=correct(idx[(f,t,arm1)],thr); y=correct(idx[(f,t,arm2)],thr)
            if x and y: a+=1
            elif x and not y: b+=1
            elif not x and y: c+=1
            else: d+=1
    p1=(a+b)/n; p2=(a+c)/n
    diff=p1-p2
    l1,u1=wilson(a+b,n,z); l2,u2=wilson(a+c,n,z)
    # correlation correction (Newcombe method 10)
    A=a; B=b; C=c; D=d
    if (A+B)*(C+D)*(A+C)*(B+D)==0:
        phi=0
    else:
        phi=(A*D-B*C)/math.sqrt((A+B)*(C+D)*(A+C)*(B+D))
    lo = diff - math.sqrt((p1-l1)**2 - 2*phi*(p1-l1)*(u2-p2) + (u2-p2)**2)
    hi = diff + math.sqrt((u1-p1)**2 - 2*phi*(u1-p1)*(p2-l2) + (p2-l2)**2)
    return diff, lo, hi, (a,b,c,d)

def cohen_h(p1,p2):
    return 2*math.asin(math.sqrt(p1))-2*math.asin(math.sqrt(p2))

print("\n"+"="*70); print("PAIRED DIFFS vs C1_A (Newcombe CI + Cohen h) @0.5")
for arm in ARMS[1:]:
    diff,lo,hi,tbl=newcombe_paired(arm,'C1_A',0.5)
    p1=arm_acc(arm,0.5)[1]; p2=arm_acc('C1_A',0.5)[1]
    h=cohen_h(p1,p2)
    print(f"  {arm:12s} d={diff*100:+5.1f}%p CI[{lo*100:+5.1f},{hi*100:+5.1f}] h={h:+.3f} (b,c)={tbl[1],tbl[2]}")

print("\nKEY GATES @0.5")
for pair in [('C4_both','C5_placebo'),('C3_rag','C5_placebo'),('C4_both','C1_A'),('C3_rag','C1_A'),('C2_gitops','C5_placebo'),('C4_both','C3_rag')]:
    diff,lo,hi,tbl=newcombe_paired(pair[0],pair[1],0.5)
    p1=arm_acc(pair[0],0.5)[1]; p2=arm_acc(pair[1],0.5)[1]; h=cohen_h(p1,p2)
    print(f"  {pair[0]:11s} - {pair[1]:11s}: d={diff*100:+5.1f}%p CI[{lo*100:+5.1f},{hi*100:+5.1f}] h={h:+.3f} b,c={tbl[1],tbl[2]}")

# ---- McNemar exact on fault-aggregated (12 items) ----
def fault_agg_correct(arm,thr):
    # per fault: fraction of 5 trials correct -> binarize at >0.5 (majority) for paired item test
    res={}
    for f in FAULTS:
        c=sum(correct(idx[(f,t,arm)],thr) for t in ['1','2','3','4','5'])
        res[f]=1 if c>=3 else 0  # majority of trials
    return res

def mcnemar_exact(arm1,arm2,thr,agg=False):
    b=c=0
    if agg:
        r1=fault_agg_correct(arm1,thr); r2=fault_agg_correct(arm2,thr)
        for f in FAULTS:
            if r1[f] and not r2[f]: b+=1
            elif not r1[f] and r2[f]: c+=1
    else:
        for f in FAULTS:
            for t in ['1','2','3','4','5']:
                x=correct(idx[(f,t,arm1)],thr); y=correct(idx[(f,t,arm2)],thr)
                if x and not y: b+=1
                elif not x and y: c+=1
    n=b+c
    if n==0: return b,c,1.0
    k=min(b,c)
    p=2*sum(math.comb(n,i)*0.5**n for i in range(0,k+1))
    return b,c,min(p,1.0)

print("\n"+"="*70); print("McNemar exact (trial-level, n=60 pairs) @0.5  [auxiliary]")
for pair in [('C4_both','C5_placebo'),('C3_rag','C5_placebo'),('C4_both','C1_A'),('C3_rag','C1_A'),('C2_gitops','C1_A'),('C4_both','C3_rag')]:
    b,c,p=mcnemar_exact(pair[0],pair[1],0.5)
    print(f"  {pair[0]:11s} vs {pair[1]:11s}: b={b} c={c} exact p={p:.4f}")
print("\nMcNemar exact (fault-aggregated majority, 12 items) @0.5")
for pair in [('C4_both','C5_placebo'),('C3_rag','C5_placebo'),('C3_rag','C1_A'),('C4_both','C1_A')]:
    b,c,p=mcnemar_exact(pair[0],pair[1],0.5,agg=True)
    print(f"  {pair[0]:11s} vs {pair[1]:11s}: b={b} c={c} exact p={p:.4f}")

# ---- 2x2 factorial decomposition (proportions) ----
print("\n"+"="*70); print("2x2 FACTORIAL DECOMPOSITION (proportion scale) @ thresholds")
for thr in [0.5,0.6,0.7]:
    c1=arm_acc('C1_A',thr)[1]; c2=arm_acc('C2_gitops',thr)[1]
    c3=arm_acc('C3_rag',thr)[1]; c4=arm_acc('C4_both',thr)[1]; c5=arm_acc('C5_placebo',thr)[1]
    gitops=(c2+c4)/2-(c1+c3)/2
    rag=(c3+c4)/2-(c1+c2)/2
    inter=(c4-c2)-(c3-c1)
    print(f"  thr={thr}: GitOps_main={gitops*100:+5.1f}%p  RAG_main={rag*100:+5.1f}%p  interaction={inter*100:+5.1f}%p  | placebo_len_eff(C5-C1)={(c5-c1)*100:+5.1f}%p")

# ---- Bootstrap CI for factorial main effects (cluster by fault) ----
def boot_factorial(thr, B=10000):
    gi=[]; ra=[]; inter=[]
    fault_list=FAULTS
    for _ in range(B):
        samp=[random.choice(fault_list) for _ in fault_list]  # resample faults (cluster)
        accs={}
        for arm in ARMS:
            tot=0; cnt=0
            for f in samp:
                for t in ['1','2','3','4','5']:
                    tot+=correct(idx[(f,t,arm)],thr); cnt+=1
            accs[arm]=tot/cnt
        c1,c2,c3,c4=accs['C1_A'],accs['C2_gitops'],accs['C3_rag'],accs['C4_both']
        gi.append((c2+c4)/2-(c1+c3)/2)
        ra.append((c3+c4)/2-(c1+c2)/2)
        inter.append((c4-c2)-(c3-c1))
    def ci(v): return (np.percentile(v,2.5),np.percentile(v,97.5))
    return (np.mean(gi),ci(gi)),(np.mean(ra),ci(ra)),(np.mean(inter),ci(inter))

print("\nBootstrap (10k, resample faults=cluster) factorial CI @0.5")
g,r,i=boot_factorial(0.5)
print(f"  GitOps main : {g[0]*100:+5.1f}%p  CI[{g[1][0]*100:+5.1f},{g[1][1]*100:+5.1f}]")
print(f"  RAG main    : {r[0]*100:+5.1f}%p  CI[{r[1][0]*100:+5.1f},{r[1][1]*100:+5.1f}]")
print(f"  interaction : {i[0]*100:+5.1f}%p  CI[{i[1][0]*100:+5.1f},{i[1][1]*100:+5.1f}]")

# ---- Per-fault forest: RAG main effect ((C3+C4)/2 - (C1+C2)/2) per fault ----
print("\n"+"="*70); print("PER-FAULT FOREST (RAG main effect & arm accs) @0.5  (5 trials each)")
print(f"  {'fault':5s} {'C1':>4s} {'C2':>4s} {'C3':>4s} {'C4':>4s} {'C5':>4s}  RAGmain  GitOpsmain")
cat={'F4':'node','F11':'net','F12':'net'}
service_rag=[]; node_rag=[]
for f in FAULTS:
    accs={}
    for arm in ARMS:
        accs[arm]=sum(correct(idx[(f,t,arm)],0.5) for t in ['1','2','3','4','5'])/5
    ragm=(accs['C3_rag']+accs['C4_both'])/2-(accs['C1_A']+accs['C2_gitops'])/2
    gm=(accs['C2_gitops']+accs['C4_both'])/2-(accs['C1_A']+accs['C3_rag'])/2
    c=cat.get(f,'service')
    (node_rag if c!='service' else service_rag).append(ragm)
    print(f"  {f:5s} {accs['C1_A']:4.1f} {accs['C2_gitops']:4.1f} {accs['C3_rag']:4.1f} {accs['C4_both']:4.1f} {accs['C5_placebo']:4.1f}  {ragm*100:+6.0f}%p  {gm*100:+6.0f}%p  [{c}]")
print(f"\n  RAG main mean: service faults={np.mean(service_rag)*100:+.1f}%p (n={len(service_rag)})  node/net faults={np.mean(node_rag)*100:+.1f}%p (n={len(node_rag)})")

# ---- category accuracy ----
print("\nCATEGORY ACCURACY @0.5")
for arm in ARMS:
    sv=sum(correct(idx[(f,t,arm)],0.5) for f in FAULTS if cat.get(f,'service')=='service' for t in ['1','2','3','4','5'])
    nd=sum(correct(idx[(f,t,arm)],0.5) for f in FAULTS if cat.get(f,'service')!='service' for t in ['1','2','3','4','5'])
    print(f"  {arm:12s} service {sv}/45={sv/45*100:4.1f}%   node/net {nd}/15={nd/15*100:4.1f}%")

# ---- measurement robustness ----
print("\n"+"="*70); print("MEASUREMENT ROBUSTNESS")
agree=[float(r['gen_agreement']) for r in rows]
print(f"  gen_agreement (k=3): mean={np.mean(agree):.3f} median={np.median(agree):.3f} min={min(agree)} dist={collections.Counter(round(a,2) for a in agree)}")
jac=[float(r['gitops_rag_jaccard']) for r in rows if r['gitops_rag_jaccard'] not in ('','None')]
print(f"  gitops_rag_jaccard: mean={np.mean(jac):.3f} max={max(jac):.3f} n>0.3={sum(1 for j in jac if j>0.3)}")
print(f"  low_quality_flag=1: {sum(1 for r in rows if r['low_quality_flag']=='1')}/300")
# judge vote agreement
jfull=0; jsplit=0
for r in rows:
    try:
        v=json.loads(r['judge_votes_json'])
        if isinstance(v,list) and len(v)>=2:
            if len(set(v))==1: jfull+=1
            else: jsplit+=1
    except: pass
print(f"  judge unanimous (m=3): {jfull}, split: {jsplit}")

# ---- threshold robustness summary of ordering ----
print("\n"+"="*70); print("ORDERING ROBUSTNESS across thresholds")
for thr in [0.5,0.6,0.7]:
    order=sorted(ARMS,key=lambda a:-arm_acc(a,thr)[1])
    accs={a:arm_acc(a,thr)[1]*100 for a in ARMS}
    print(f"  thr={thr}: " + " > ".join(f"{a.split('_')[0]}({accs[a]:.0f})" for a in order))

# boundary score=0.5 reliance
print("\nSCORE=0.5 BOUNDARY RELIANCE per arm")
for arm in ARMS:
    scores=[float(idx[(f,t,arm)]['rep_correctness_score']) for f in FAULTS for t in ['1','2','3','4','5']]
    n_correct=sum(1 for s in scores if s>=0.5)
    n_exactly05=sum(1 for s in scores if abs(s-0.5)<1e-9)
    print(f"  {arm:12s} correct@0.5={n_correct} of which exactly 0.5: {n_exactly05} ({(n_exactly05/n_correct*100) if n_correct else 0:.0f}%) | score dist={collections.Counter(round(s,2) for s in scores)}")
