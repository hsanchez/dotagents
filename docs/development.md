# Development and testing

Install dependencies and run the full validation path from the repository
root:

```bash
uv sync
uv run prek run --all-files
uv run pytest
```

The repository smoke test installs this checkout into a temporary consuming
repository and verifies initialization, `doctor`, and the dangerous-git
guardrail:

```bash
sh tests/smoke-test
```

The self-host smoke test uses a temporary source-checkout copy and verifies
that source `scripts/*` files remain regular files while generated provider
links and runtime copies work:

```bash
sh tests/smoke-test-self-host
```

## Maintainer self-hosting

The dotagents checkout can materialize its own runtime for agentic development.
The maintainer-only option preserves source files under `scripts/` as regular
files while still generating `.agents/` and provider configuration:

```bash
uv run dotagents init --self-host --for claude --for codex
uv run dotagents doctor
```

The option is intentionally hidden from normal CLI help and is rejected for
any repository other than the dotagents source checkout. The self-host mode is
recorded in `.agents/dotagents.lock`; subsequent `sync`, `update`, and
`doctor` commands preserve it automatically.

The global bootstrap has a separate smoke test using a fake home directory:

```bash
sh tests/smoke-test-dot
```

To exercise its private-`uv` download and checksum-failure paths, which use
the network, run:

```bash
DOTAGENTS_SMOKE_TEST_UV_DOWNLOAD=1 sh tests/smoke-test-dot
```
