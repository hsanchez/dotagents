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

The global bootstrap has a separate smoke test using a fake home directory:

```bash
sh tests/smoke-test-dot
```

To exercise its private-`uv` download and checksum-failure paths, which use
the network, run:

```bash
DOTAGENTS_SMOKE_TEST_UV_DOWNLOAD=1 sh tests/smoke-test-dot
```
