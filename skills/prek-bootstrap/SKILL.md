---
name: prek-bootstrap
description: Install prek as dev dependency and scaffold a minimal prek.toml so `uv run prek run --all-files` works. Run on demand when prek or its config is missing (dotagents doctor surfaces this).
---

# prek-bootstrap

The project rules require `uv run prek run --all-files` before every commit. This skill bootstraps that toolchain in a repo that does not yet have it.

Run this skill only when the user asks for it, or when `dotagents doctor` reports `prek: missing ...`. The doctor warning also tells the user to enable this skill first (add `skill prek-bootstrap` to their `Skillfile` and run `uv run dotagents sync`) since it is opt-in.

Never run silently at session startup - it mutates `pyproject.toml` and writes a config file.

## Steps

1. **Check state.** Report what is missing before changing anything:
  - Binary: `command -v prek`
  - Config: `prek.toml` or `.pre-commit-config.yaml` at repo root

2. **Install prek** as a dev dependency if the binary is missing:

  ```bash
  uv add --dev prek
  ```

3. **Scaffold `prek.toml`** if not config exists. Do not override an existing config - ask the user before modifying it.

  Minimal starting point (adjust per project shape):

  ```toml
  [[repos]]
  repo = "local"
  hooks = [
    { id = "ruff-format", name = "ruff format", language = "system", entry = "uv run ruff format --check src tests", pass_filenames = false },
    { id = "ruff-check", name = "ruff check", language = "system", entry = "uv run ruff check src tests", pass_filenames = false },
    { id = "ty", name = "ty", language = "system", entry = "uv run ty check", pass_filenames = false },
    { id = "pytest", name = "pytest", language = "system", entry = "uv run pytest", pass_filenames = false },
  ]
  ```

  Hook versions above are illustrative. Confirm the latest tags with the user or leave a follow-up note.

4. **Register the git hook** so prek runs on commit:

  ```bash
  uv run prek install
  ```

5. **Verify.** Run once against the whole tree and report the result:

  ```bash
  uv run prek run --all-files
  ```

## Notes

- Idempotent: re-running is safe. If `prek` is already a dep and a config already exists, report the state and stop.
- Never overwrite `prek.toml` or `.pre-commit-config.yaml` without explicit confirmation.
- If the repo uses tools other than ruff / ty (e.g., mypy, black), ask the user which hooks to include instead of assuming.
