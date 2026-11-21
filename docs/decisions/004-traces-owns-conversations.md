# 004 Traces owns conversations; memory keeps pointers

Conversation histories are never markdown memory. Product jsonl stays in the vendor folder. agents-traces ingest is the derived log (`origin=ingested` plus live MCP). agents-memory `ingest_catalog` writes titles + paths only. `session_snap` / `session_grep` / `session_tail` on the memory MCP are thin wrappers: baton header stays here, message bodies come from `agents_traces.session_view`. `auto_trace_mcp` stays a traces client wrapped around this server.

Do not scrape product jsonl from memory again. If a session read needs a new field, add it in traces.

`agents-brain` later bundles these packages; it does not collapse the stores.
