# Research goal priority note

- `research_target` returns `superseded_by_research_chain` whenever `research_chain_order` exists in config (`agent/planner.py`, `_plan_research_target`); the shipped config always defines that key (`agent/config.json`).
- This guard is unconditional: it also skips `research_target` when the chain has no built ResearchCenter, no valid ready basic tech, or an empty configured order.
- The planner records the reason in `skipped` and continues to other goals; the chain itself requires a built ResearchCenter.
- Recommendation: eventually make `research_target` a deliberate fallback only when `research_chain` cannot provide a target, with explicit precedence tests. Do not change that behavior in this ResearchCenter setup change; avoid silently changing research ordering.
