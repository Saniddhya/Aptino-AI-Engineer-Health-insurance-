"""Local, explainable hybrid retrieval. No network/model download required for the demo."""
from __future__ import annotations
import json, math, re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

TOKEN = re.compile(r"[a-z0-9]+")
def tokens(text: str) -> list[str]: return TOKEN.findall(text.lower())

class PolicyChunk(dict):
    pass

def structural_chunks(pages: Iterable[dict], source='policy.pdf') -> list[PolicyChunk]:
    """Keep headings and numbered/list clauses intact; never fixed-width split."""
    out=[]
    for page_obj in pages:
        page=int(page_obj['page']); section='General'
        blocks=[]; current=[]
        heading_words={'definitions','exclusions','extensions','claims procedure','portability','waiting period','critical illness'}
        for line in page_obj['text'].splitlines():
            line=' '.join(line.split())
            if not line: continue
            if line.startswith('# '):
                if current: blocks.append(('\n'.join(current)).strip()); current=[]
                section=line[2:].strip(); continue
            lower=line.lower()
            is_heading=(lower in heading_words or (len(line)>5 and line==line.upper() and any(c.isalpha() for c in line) and 'UNIVERSAL SOMPO' not in line))
            is_clause=bool(re.match(r'^(\d+\.|[a-z]\)|[•])\s+',line))
            if is_heading:
                if current: blocks.append(('\n'.join(current)).strip()); current=[]
                section=line.title(); continue
            if is_clause and current and len(' '.join(current))>180:
                blocks.append(('\n'.join(current)).strip()); current=[]
            current.append(line)
        if current: blocks.append(('\n'.join(current)).strip())
        for ordinal, text in enumerate(blocks, 1):
            slug=re.sub('[^a-z0-9]+','_',section.lower()).strip('_')[:36] or 'general'
            out.append(PolicyChunk(chunk_id=f'policy_p{page:02d}_{slug}_{ordinal:03d}', source=source, page=page, section=section, subsection=None, text=text))
    return out

class HybridRetriever:
    """BM25 + hashed dense cosine + RRF + post-fusion lexical reranker."""
    def __init__(self, chunks: list[dict], rrf_k=60):
        self.chunks=chunks; self.rrf_k=rrf_k; self.docs=[tokens(c['text']+' '+c['section']) for c in chunks]
        self.df=Counter(t for d in self.docs for t in set(d)); self.avgdl=sum(map(len,self.docs))/max(1,len(self.docs))
    def bm25(self,q):
        qt=tokens(q); n=len(self.docs); scores=[]
        for d in self.docs:
            tf=Counter(d); score=0
            for t in qt:
                if t not in tf: continue
                idf=math.log(1+(n-self.df[t]+.5)/(self.df[t]+.5)); score += idf*tf[t]*2.2/(tf[t]+1.2*(1-.75+.75*len(d)/self.avgdl))
            scores.append(score)
        return scores
    def dense(self,q):
        # Stable 256-d hashing representation: semantic-ish term matching fallback, cacheable and offline.
        def vec(ts):
            v=defaultdict(float)
            for t in ts: v[hash(t)%256]+=1
            norm=math.sqrt(sum(x*x for x in v.values())) or 1
            return {k:x/norm for k,x in v.items()}
        a=vec(tokens(q)); scores=[]
        for d in self.docs:
            b=vec(d); scores.append(sum(v*b.get(k,0) for k,v in a.items()))
        return scores
    def search(self,q, top_n=8, top_k=5):
        bm=self.bm25(q); de=self.dense(q)
        br=sorted(range(len(self.chunks)),key=lambda i:bm[i],reverse=True)[:top_n]
        dr=sorted(range(len(self.chunks)),key=lambda i:de[i],reverse=True)[:top_n]
        fused=defaultdict(float)
        for ranking in (br,dr):
            for rank,i in enumerate(ranking,1): fused[i]+=1/(self.rrf_k+rank)
        qset=set(tokens(q)); candidates=[]
        for i, f in fused.items():
            overlap=len(qset & set(self.docs[i])) / max(1,len(qset))
            rerank=.70*f*100 + .30*overlap
            candidates.append((rerank,i,f))
        answer=[]
        for rerank,i,f in sorted(candidates,reverse=True)[:top_k]:
            answer.append({**self.chunks[i], 'dense_score':round(de[i],4),'bm25_score':round(bm[i],4),'fusion_score':round(f,5),'rerank_score':round(rerank,4)})
        return answer

def load_policy(path: str | Path) -> list[dict]:
    p=Path(path)
    if p.suffix.lower()=='.pdf':
        from pypdf import PdfReader
        pages=[{'page':i+1,'text':page.extract_text() or ''} for i,page in enumerate(PdfReader(str(p)).pages)]
    else: pages=json.loads(p.read_text(encoding='utf8'))['pages']
    chunks=structural_chunks(pages,p.name)
    if not chunks: raise ValueError('Policy parsing produced no structural chunks')
    return chunks
