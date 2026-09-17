from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.schemas import Claim
from app.service import analyze
def run():
    expected_map=json.loads((ROOT/'evaluation/expected_results.json').read_text())
    cases=[]
    public=ROOT/'candidate_data'/'public_test_cases.json'
    official_public=public.exists()
    if official_public: cases += json.loads(public.read_text())
    else: cases += json.loads((ROOT/'data/cases'/'public_cases.json').read_text())
    candidate=ROOT/'data/cases'/'candidate_cases.json'
    if candidate.exists(): cases += json.loads(candidate.read_text())
    results=[]
    latencies=[]
    for raw in cases:
        start=time.perf_counter()
        r=analyze(Claim(**raw))
        dur=(time.perf_counter()-start)*1000
        latencies.append(dur)
        expected=None if official_public and raw['case_id'].startswith('PUB-') else expected_map.get(raw['case_id'])
        results.append({
            'case_id':r.case_id,
            'expected_decision':expected,
            'actual_decision':r.decision,
            'decision_correct':None if expected is None else r.decision==expected,
            'citation_correct':bool(r.citations),
            'retrieval_metrics':{'retrieved_evidence_count':len(r.citations)},
            'validation_status':r.validation.status,
            'latency_ms':dur
        })
    scored=[x for x in results if x['decision_correct'] is not None]; total=len(scored) or 1
    summary={
        'total_cases':len(results),
        'scored_cases':len(scored),
        'decision_accuracy':None if not scored else sum(x['decision_correct'] for x in scored)/total,
        'citation_hit_rate':sum(x['citation_correct'] for x in results)/max(1,len(results)),
        'validation_rate':sum(x['validation_status']=='PASS' for x in results)/max(1,len(results)),
        'abstention_count':sum(x['actual_decision']=='NEEDS_REVIEW' for x in results),
        'avg_latency_ms':sum(latencies)/max(1,len(latencies)),
        'cases':results
    }
    (ROOT/'evaluation/results.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__': run()
