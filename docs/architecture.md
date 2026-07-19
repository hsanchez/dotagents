# Runtime architecture

dotagents separates reusable package assets from generated output in a
consuming repository.

```text
dotagents package       source assets and provider adapters
.agents/                managed runtime
.agents/skills/         selected shared skills
.agents/scripts/        selected shared scripts
.agents/providers/      provider adapters and configuration
.agents/dotagents.lock  ownership and drift record
.rules                  generated shared rules
.rules.local            repository-specific extension
provider files          generated provider-facing links and files
```

The consuming repository does not receive the full package source tree. It
receives only the runtime required by its selected providers and skills.

Do not edit managed `.agents/*` files directly. Change package sources or the
`Skillfile`, then run `sync` or `update`. The lockfile is the ownership source
for cleanup and drift detection.
