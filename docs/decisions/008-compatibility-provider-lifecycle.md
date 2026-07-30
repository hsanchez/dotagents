# Compatibility providers remain explicit and opt-in

Provider lifecycle is declared in `agents.toml` with `status` and `default`
metadata. Active providers participate in implicit initialization;
compatibility providers remain available through explicit selection,
`--for all`, and existing lockfiles.

## Status

accepted

## Considered Options

- Remove Gemini CLI support; rejected because Enterprise licenses and API-key
  authentication remain supported.
- Alias `gemini` to `agy`; rejected because the CLIs have distinct
  configuration roots, hook contracts, permission models, and assets.
- Keep Gemini in the implicit default set; rejected because Google directs
  individual users to Antigravity CLI.

## Consequences

- Antigravity CLI (`agy`) is the primary Google provider.
- Gemini CLI is a compatibility provider for Enterprise/API-key users.
- `dotagents init` selects active providers; `dotagents init --for all`
  includes compatibility providers.
- Existing lockfiles remain authoritative, so upgrades never remove or
  replace a configured compatibility provider.
