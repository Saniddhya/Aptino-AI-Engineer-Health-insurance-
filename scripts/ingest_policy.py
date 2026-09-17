"""Validate and cache policy chunks. PDF input is supported via pypdf."""
import json, os, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
if str(root) not in sys.path: sys.path.insert(0,str(root))
from app.retrieval import load_policy

default_policy=root/'policy'/'USGIC-CSCIndividualHealthInsurance_2017-2018.pdf'
policy=Path(os.getenv('POLICY_PATH',default_policy if default_policy.exists() else root/'data/policy/demo_policy.json'))
chunks=load_policy(policy)
out=root/'data/index/policy_index.json'; out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({'source':str(policy),'chunks':chunks},indent=2),encoding='utf8')
print(f'Indexed {len(chunks)} structural chunks from {policy}')
