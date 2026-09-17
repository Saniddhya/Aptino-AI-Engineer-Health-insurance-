from app.retrieval import structural_chunks, HybridRetriever
from app.schemas import Claim
from app.service import analyze
def test_structural_chunks_preserve_metadata():
    chunks=structural_chunks([{'page':7,'text':'# Limits\n\nA limit applies.'}])
    assert chunks[0]['page']==7 and chunks[0]['section']=='Limits' and chunks[0]['chunk_id']
def test_hybrid_retrieves_exact_waiting_term():
    chunks=structural_chunks([{'page':1,'text':'# Waiting\n\nA 24 month waiting period applies.'}])
    assert HybridRetriever(chunks).search('waiting period')[0]['section']=='Waiting'
def test_rrf_and_rerank_scores_present():
    chunks=structural_chunks([{'page':1,'text':'# Limits\n\nSum insured limit.'}])
    result=HybridRetriever(chunks).search('sum insured limit')[0]
    assert result['fusion_score']>0 and 'rerank_score' in result
def test_abstains_on_missing_claim_material():
    response=analyze(Claim(case_id='missing',treatment='hospitalisation',sum_insured=1000))
    assert response.decision=='NEEDS_REVIEW' and response.validation.status=='PASS'
def test_api_contract():
    from fastapi.testclient import TestClient
    from app.main import app
    c=TestClient(app); assert c.get('/health').status_code==200
    assert c.post('/analyze',json={'case_id':'bad'}).status_code==404
    assert c.post('/analyze',json={'case':{'case_id':'api','treatment':'hospitalisation','sum_insured':1000}}).status_code==200
