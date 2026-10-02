"""Analytics & recommendation engine — pure functions, no LLM.

Keeping insight logic here (not in prompts) makes it testable, auditable, and
deterministic. Tools call these and return structured summaries the LLM narrates.
"""
