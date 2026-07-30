"""Classify shell commands that can destroy local or remote git state."""

from __future__ import annotations

import re
import shlex

_ALWAYS_BLOCK: dict[str, str] = {
  "push": "git push requires explicit human approval",
  "restore": "git restore discards working tree changes — use git stash to preserve them",
}

_GLOBAL_FLAGS_WITH_ARG: frozenset[str] = frozenset(
  {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--super-prefix",
  }
)

_GLOBAL_FLAGS_SOLO: frozenset[str] = frozenset(
  {
    "--no-pager",
    "--paginate",
    "-p",
    "--bare",
    "--no-replace-objects",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--no-optional-locks",
  }
)

_GLOBAL_FLAG_PREFIXES: tuple[str, ...] = (
  "--git-dir=",
  "--work-tree=",
  "--namespace=",
  "--exec-path=",
  "--super-prefix=",
)

_WRAPPER_SPECS: dict[str, tuple[frozenset[str], frozenset[str], bool]] = {
  "env": (
    frozenset({"-u", "--unset"}),
    frozenset({"-i", "-0", "--ignore-environment", "--null"}),
    True,
  ),
  "command": (
    frozenset(),
    frozenset({"-p", "-V", "-v"}),
    False,
  ),
  "exec": (
    frozenset({"-a"}),
    frozenset({"-c", "-l"}),
    False,
  ),
  "sudo": (
    frozenset({"-C", "-D", "-g", "-h", "-p", "-R", "-r", "-t", "-T", "-u"}),
    frozenset({"-A", "-B", "-b", "-E", "-H", "-n", "-P", "-S"}),
    True,
  ),
  "nice": (
    frozenset({"-n"}),
    frozenset(),
    False,
  ),
  "nohup": (
    frozenset(),
    frozenset(),
    False,
  ),
}


def _is_git(token: str) -> bool:
  return token == "git" or token.endswith("/git")


def _uses_sudo(segment: str) -> bool:
  try:
    tokens = shlex.split(segment)
  except ValueError:
    tokens = segment.split()

  index = 0
  while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
    index += 1

  while index < len(tokens):
    executable = tokens[index]
    name = executable.rsplit("/", 1)[-1]
    if name == "sudo":
      return True
    if name not in _WRAPPER_SPECS:
      return False

    flags_with_argument, _flags_solo, allows_environment = _WRAPPER_SPECS[name]
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
      token = tokens[index]
      base = token.split("=")[0] if "=" in token else token
      index += 1 if "=" in token or base not in flags_with_argument else 2
    if allows_environment:
      while index < len(tokens) and re.match(
        r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]
      ):
        index += 1
  return False


def _parse_git_call(segment: str) -> tuple[str, list[str]] | None:
  try:
    tokens = shlex.split(segment)
  except ValueError:
    tokens = segment.split()

  index = 0
  while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
    index += 1

  while index < len(tokens) and tokens[index] in _WRAPPER_SPECS:
    flags_with_argument, _flags_solo, allows_environment = _WRAPPER_SPECS[tokens[index]]
    index += 1

    while index < len(tokens) and tokens[index].startswith("-"):
      token = tokens[index]
      base = token.split("=")[0] if "=" in token else token
      if base in flags_with_argument:
        index += 1 if "=" in token else 2
      else:
        index += 1

    if allows_environment:
      while index < len(tokens) and re.match(
        r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]
      ):
        index += 1

  if index >= len(tokens) or not _is_git(tokens[index]):
    return None
  index += 1

  while index < len(tokens):
    token = tokens[index]
    if token in _GLOBAL_FLAGS_WITH_ARG:
      index += 2
    elif token in _GLOBAL_FLAGS_SOLO or any(
      token.startswith(prefix) for prefix in _GLOBAL_FLAG_PREFIXES
    ):
      index += 1
    elif token.startswith("-"):
      index += 1
    else:
      break

  if index >= len(tokens):
    return None
  return tokens[index], tokens[index + 1 :]


def _short_flag(arguments: list[str], character: str) -> bool:
  return any(
    argument.startswith("-")
    and not argument.startswith("--")
    and character in argument
    for argument in arguments
  )


def _check_segment(segment: str) -> str | None:
  segment = re.sub(r"^[\s$(]+", "", segment).rstrip(")")
  if _uses_sudo(segment):
    return "sudo requires explicit human approval"
  parsed = _parse_git_call(segment.strip())
  if parsed is None:
    return None

  subcommand, arguments = parsed
  if subcommand in _ALWAYS_BLOCK:
    return _ALWAYS_BLOCK[subcommand]

  if subcommand == "reset" and "--hard" in arguments:
    return "git reset --hard discards committed work — use --soft or --mixed"

  if subcommand == "clean":
    if "--force" in arguments or _short_flag(arguments, "f"):
      return "git clean -f removes untracked files irreversibly"

  if subcommand == "branch":
    if "-D" in arguments or _short_flag(arguments, "D"):
      return "git branch -D force-deletes branches — requires explicit human approval"
    has_delete = (
      "--delete" in arguments
      or "-d" in arguments
      or _short_flag(arguments, "d")
    )
    has_force = "--force" in arguments or _short_flag(arguments, "f")
    if has_delete and has_force:
      return "git branch --delete --force force-deletes branches"

  if subcommand == "checkout":
    if "--force" in arguments or _short_flag(arguments, "f"):
      return "git checkout -f discards local changes — use git stash first"
    if arguments and arguments[0] == ".":
      return "git checkout . discards working tree changes"
    if "--" in arguments and arguments.index("--") < len(arguments) - 1:
      return "git checkout -- <paths> discards working tree changes"

  if subcommand == "switch":
    if (
      "--force" in arguments
      or "--discard-changes" in arguments
      or _short_flag(arguments, "f")
    ):
      return "git switch --force discards local changes — use git stash first"

  return None


def dangerous_command_reason(command: str) -> str | None:
  """Return the first destructive-git reason found in a shell command."""
  for segment in re.split(r"&&|\|\||[;|\n]", command):
    reason = _check_segment(segment)
    if reason:
      return reason
  return None
