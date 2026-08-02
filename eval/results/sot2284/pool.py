"""Pool self-mirror A/B shards -> pooled winrate_a + Wilson95 (draws excluded)."""
import glob, json, math, sys

def wilson(w,n,z=1.96):
    if n==0: return (0.0,1.0)
    p=w/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d
    m=(z/d)*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return (max(0,c-m),min(1,c+m))

def pool(pattern):
    wa=wb=draws=faults=nm=0
    files=sorted(glob.glob(pattern))
    for fp in files:
        r=json.load(open(fp))
        wa+=r['wins_a']; wb+=r['wins_b']; draws+=r['draws']; nm+=r['n_matches']
        faults+=r['rejects']+r['exceptions']+r['fallbacks_a']+r['fallbacks_b']
        faults+=r['budget_violations_a']+r['budget_violations_b']
    decided=wa+wb
    p=wa/decided if decided else None
    lo,hi=wilson(wa,decided)
    return dict(files=len(files),n_matches=nm,wins_a=wa,wins_b=wb,draws=draws,
                decided=decided,winrate_a=p,wilson95=[lo,hi],
                curr_point=(1-p) if p is not None else None,faults=faults)

if __name__=='__main__':
    for pat in sys.argv[1:]:
        r=pool(pat)
        lo,hi=r['wilson95']
        print(f"{pat}")
        print(f"  shards={r['files']} n={r['n_matches']} A={r['wins_a']} B={r['wins_b']} draws={r['draws']} faults={r['faults']}")
        if r['winrate_a'] is not None:
            print(f"  cand winrate_a={r['winrate_a']:.4f}  Wilson95=[{lo:.4f},{hi:.4f}]  curr_point={r['curr_point']:.4f}  GATE(lo>curr_point)={'PASS' if lo>r['curr_point'] else 'FAIL'}")
