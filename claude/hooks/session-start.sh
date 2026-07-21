#!/bin/sh

set -eu

project_directory=${CLAUDE_PROJECT_DIR:-.}
meta_skill="$project_directory/.agents/skills/dotagents-discovery/SKILL.md"
preface='dotagents discovery is enabled. Read the injected meta-skill before selecting a task skill.'

if [ ! -f "$meta_skill" ]; then
  printf '%s\n' '{"priority":"INFO","message":"dotagents discovery meta-skill was not found in .agents/skills."}'
  exit 0
fi

if command -v jq >/dev/null 2>&1; then
  {
    printf '%s\n\n' "$preface"
    cat "$meta_skill"
  } | jq -Rs '{priority: "IMPORTANT", message: .}'
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  META_SKILL_PATH="$meta_skill" PREFACE="$preface" python3 - <<'PY'
import json
import os
from pathlib import Path

meta_skill = Path(os.environ["META_SKILL_PATH"]).read_text(encoding="utf-8")
message = f"{os.environ['PREFACE']}\n\n{meta_skill}"
print(json.dumps({"priority": "IMPORTANT", "message": message}))
PY
  exit 0
fi

printf '%s\n' '{"priority":"INFO","message":"dotagents discovery meta-skill is installed, but jq or python3 is required to inject it."}'
