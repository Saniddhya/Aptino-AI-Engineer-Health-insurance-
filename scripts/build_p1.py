#!/usr/bin/env python3
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(script_dir)
target = os.path.join(root, 'app', 'agents.py')

content = '''from __future__ import annotations
import time
import logging
import re
from datetime import date
from .schemas import Claim, Citation, Finding, TraceEvent

logger = logging.getLogger(__name__)

def _elapsed(name, started, status, summary): 
    return TraceEvent(agent=name, status=status, duration_ms=int((time.perf_counter()-started)*1000), summary=summary)

def _days_between(start, end):
    try: 
        return (date.fromisoformat(end)-date.fromisoformat(start)).days
    except (TypeError, ValueError): 
        return None

def _get_policy_concepts(evidence: list[dict]) -> dict:
    text = ' '.join(e['text'].lower() for e in evidence)
    concepts = {
        'has_waiting_period': any(phrase in text for phrase in ['waiting period', '24 month', '30 days']),
        'waiting_period_months': None,
        'has_experimental_exclusion': any(phrase in text for phrase in ['experimental', 'unproven', 'investigational']),
        'has_cosmetic_exclusion': any(phrase in text for phrase in ['cosmetic', 'aesthetic']),
        'has_domiciliary': 'domiciliary' in text,
        'has_day_care': any(phrase in text for phrase in ['day care', 'day-care', 'day care treatment']),
        'has_room_rent_limit': any(phrase in text for phrase in ['room rent', 'room category', 'single room']),
        'has_sub_limits': 'sub-limit' in text or 'sub limit' in text,
        'has_pre_existing_clause': any(phrase in text for phrase in ['pre-existing', 'pre existing', 'waiting period']),
        'has_hospital_definition': 'hospital' in text and ('definition' in text or 'means' in text),
        'has_portability': any(phrase in text for phrase in ['portability', 'continuous coverage', 'prior insurer']),
    }
    waits = re.findall(r'(\\d+)\\s*(month|months|day|days)\\s*(waiting|period)?', text)
    if waits:
        for num, unit, _ in waits:
            num = int(num)
            if unit.startswith('month'):
                concepts['waiting_period_months'] = num
                break
            elif unit.startswith('day') and num < 100:
                pass
    return concepts

'''

with open(target, 'w') as f:
    f.write(content)

print(f"Part 1 written: {len(content)} chars")