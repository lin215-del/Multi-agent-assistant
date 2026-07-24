"""FastAPI multi-agent orchestration package.

Agent modules:
  tracing    - trace() and now_ms() shared utilities
  state      - AgentState dataclass
  intent     - expand_intent (question intent expansion)
  router     - route_question + is_study_place_intent
  health     - health_answer safety template
  study_place- local library-hours file reader
  retriever  - RAGFlow retrieval + grounded answer extraction
  tools      - GPA / weighted-average calculation
  quality    - quality gate checks + bigram helpers
  rewrite    - LLM + template-based query rewrite
  reflection - final reflection pass
  answer     - LLM answer polish
  multimodal - multimodal asset loading
  graph      - LangGraph orchestration (no business logic)
"""
