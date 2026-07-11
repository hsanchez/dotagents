# Deterministic compiler layer

dotagents adds a deterministic compiler layer beside the existing runtime
materializer. Higher-level sources such as templates and MCP capability
snapshots compile into managed `.agents/` artifacts, with source lineage recorded
in `.agents/build/manifest.json` and final file ownership recorded in
`.agents/dotagents.lock`.

This keeps the stable package-driven runtime model while allowing dotagents to
generate repo-local agent environments from inspectable inputs. Compilation is
deterministic by default; live discovery and LLM-at-compile-time behavior remain
explicit follow-up capabilities because they require stronger audit, cache, and
reproducibility semantics.
