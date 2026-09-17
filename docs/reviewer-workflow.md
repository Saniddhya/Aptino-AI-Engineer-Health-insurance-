# Reviewer Workflow Guide

This document describes the intended operational workflow for an insurance analyst using the Aptino Claim Decision Engine.

## 1. Case Initiation
The reviewer starts by selecting a case from the public fixtures or uploading a custom claim JSON. 

**Action**: Click `Analyze Claim`.

## 2. Reviewing the Investigation
The system performs a multi-agent analysis. The reviewer should inspect the results in the following order:

### Step A: The Decision & Confidence
Check the **Final Decision** (e.g., `ADMISSIBLE` or `NEEDS_REVIEW`). If the decision is `NEEDS_REVIEW`, the reviewer should immediately skip to the "Missing Evidence" section.

### Step B: Decision Drivers
Review the **Decision Drivers** list. These are the high-level reasons why the decision was reached (e.g., "✓ Treatment type falls within coverage").

### Step C: The Evidence Matrix
This is the core of the audit. The reviewer should verify:
- **Dimension**: Is the correct policy aspect being evaluated?
- **Claim Fact**: Is the system interpreting the claim data correctly?
- **Status**: Does the status (`SUPPORTED`, `MISSING`, etc.) match the evidence provided?
- **Conclusion**: Is the conclusion a logical derivation of the evidence?

### Step D: Policy Citations
For any suspicious or critical finding, the reviewer should expand the **Policy Evidence Trace**.
- Verify the **Page** and **Section**.
- Read the **Exact Evidence** text to ensure the LLM hasn't hallucinated a clause.

## 3. Handling Abstentions (`NEEDS_REVIEW`)
When the system abstains:
1. Read the **Reason** in the Decision Explanation.
2. Inspect the **Missing Evidence Intelligence** section.
3. Identify the **Recommended Next Action** (e.g., "Obtain hospital accreditation documentation").

## 4. Finalizing the Decision
The reviewer has four possible actions:
- **Approve**: The automated decision is correct and fully supported.
- **Send to Review**: The case is complex and requires senior adjuster oversight.
- **Request Evidence**: The system correctly identified a gap; the reviewer initiates a request to the claimant.
- **Override**: The reviewer disagrees with the automated decision based on external authority or deeper insight. (Requires a reason).

## 5. Auditability
Every action taken by the reviewer and every step taken by the system is recorded in the **Audit Trail**, ensuring a complete provenance chain for the final claim determination.
