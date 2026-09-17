from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, model_validator
from .schemas import Claim, DecisionResponse, ReviewAction
from .service import analyze, known_case, save_review, get_reviews
app=FastAPI(title='Aptino Policy-Aware Claim Decision Engine',version='0.1.0')
class AnalyzeRequest(BaseModel):
    case: dict | None = None
    case_id: str | None = None
    @model_validator(mode='after')
    def exactly_one_source(self):
        if bool(self.case) == bool(self.case_id): raise ValueError('Provide exactly one of case or case_id.')
        return self
@app.get('/health')
def health(): return {'status':'ok','service':'claim-decision-engine'}
@app.post('/analyze',response_model=DecisionResponse)
def analyze_claim(request: AnalyzeRequest):
    try:
        claim=Claim(**request.case) if request.case else known_case(request.case_id or '')
        if claim is None: raise HTTPException(status_code=404,detail='Unknown case_id.')
        return analyze(claim)
    except HTTPException: raise
    except Exception as exc: raise HTTPException(status_code=503,detail=f'Policy analysis unavailable: {exc}')
@app.post('/review')
def submit_review(review: ReviewAction):
    try:
        save_review(review)
        return {'status': 'success', 'message': 'Review submitted successfully'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get('/reviews/{case_id}')
def get_case_reviews(case_id: str):
    return get_reviews(case_id)
