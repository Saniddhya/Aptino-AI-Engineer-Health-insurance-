# Project Exploration Plan

The goal is to identify issues preventing the product from running or being tested effectively.

## Tasks

- [ ] **LLM Provider Analysis**
    - Read `app/main.py`, `app/service.py`, `app/agents.py`, and `app/llm/provider.py`.
    - Identify how the LLM is instantiated and used.
- [ ] **Configuration Audit**
    - Identify required environment variables and configuration settings.
    - Check for missing config files or default values that might break in non-mock mode.
- [ ] **Frontend Review**
    - Analyze `frontend/streamlit_app.py` for configuration needs or obvious issues.
- [ ] **Dependency Check**
    - Review `requirements.txt` for missing libraries required by the identified LLM providers.
- [ ] **TODO/FIXME Search**
    - Search the codebase for `TODO` and `FIXME` comments.
- [ ] **Final Summary**
    - Compile findings and suggest updates for "production-ready" testing.

