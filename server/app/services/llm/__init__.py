"""Provider-agnostic LLM gateway package.

WrzDJSet (and any future agentic feature) MUST call LLMs only through
`app.services.llm.gateway`. Direct provider SDK imports are forbidden in
feature code — provider/model identifiers are data, not imports.
"""
