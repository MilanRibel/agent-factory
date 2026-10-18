"""Claude Code settings tests: a PR cannot weaken the permission policy unnoticed.

The whole policy for .claude/settings.json sits in this file:
- every rule in MUST_DENY_BASH and MUST_DENY_READ is a deny rule;
- every rule in MUST_ASK_OR_DENY is an ask or a deny rule;
- every protected path has its `Edit` ask rule;
- no allow rule allows every command, covers a sample command of a rule above,
  or lets a file-editing tool overlap a protected path;
- `defaultMode` is never `bypassPermissions`;
- .gitignore keeps .claude/settings.local.json out of git.

Rules are matched as https://code.claude.com/docs/en/permissions describes them.
In a Bash rule, `*` matches any text, and a trailing ` *` that is the only
wildcard also matches the bare command. Edit rules use gitignore syntax and cover
every built-in file-editing tool; `/path` in project settings starts at the
directory the session starts in, the repository root. Both checks on allow rules
work with samples: sample commands for Bash, and for paths each side's pattern
with its wildcards filled in (plus the protected files on disk), matched against
the other side's pattern.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
GITIGNORE = REPO_ROOT / ".gitignore"
LOCAL_SETTINGS = ".claude/settings.local.json"

Settings = dict[str, Any]
Mutation = Callable[[Settings, list[str]], None]  # edits settings and .gitignore lines

# Deny rules for commands, each with sample commands it must stop. An allow rule
# that matches a sample command covers the rule.
MUST_DENY_BASH: dict[str, tuple[str, ...]] = {
    "Bash(sudo *)": ("sudo ls /root",),
    "Bash(rm -rf *)": ("rm -rf build",),
    "Bash(curl *)": ("curl https://example.com",),
    "Bash(wget *)": ("wget https://example.com",),
    "Bash(gh pr merge *)": ("gh pr merge", "gh pr merge 1 --squash"),
    "Bash(git push --force*)": (
        "git push --force origin main",
        "git push --force-with-lease",
    ),
    "Bash(git push * --force*)": ("git push origin main --force",),
    "Bash(gh auth token*)": ("gh auth token",),
    "Bash(gh api *rulesets*)": ("gh api repos/example-owner/example-repo/rulesets",),
    "Bash(*set-rulesets.sh*--apply*)": ("scripts/set-rulesets.sh --apply",),
}
MUST_DENY_READ = ("Read(./.env*)", "Read(~/.ssh/**)", "Read(~/.aws/**)")
# Commands that need at least a human yes, with sample commands.
MUST_ASK_OR_DENY: dict[str, tuple[str, ...]] = {
    "Bash(git push *)": ("git push", "git push origin main"),
    "Bash(gh pr create *)": ("gh pr create --draft",),
    "Bash(gh issue create *)": ("gh issue create --title example",),
    "Bash(gh api *)": ("gh api user",),
    "Bash(uv add *)": ("uv add requests",),
    "Bash(docker *)": ("docker run --rm alpine",),
}
SAMPLE_COMMANDS = {**MUST_DENY_BASH, **MUST_ASK_OR_DENY}

# Protected paths, written as in AGENTS.md: a directory ends with "/".
# #8 takes this list from AGENTS.md.
PROTECTED_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/",
    ".github/",
    "docs/adr/",
    "uv.lock",
    "scripts/set-rulesets.sh",
    "images/**/Dockerfile",
)
# Built-in tools that write files. Path checks consult Edit rules only, but an
# allow rule for any of these tools is held to the same check.
FILE_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# A gitignore glob, token by token: `**` crosses directories, `*`, `?` and a
# `[...]` class do not, and `/**/` also matches a single `/`.
GLOB_TOKEN = re.compile(r"/\*\*/|\*\*|\*|\?|\[!?[^\]]+\]|.", re.DOTALL)
GLOB_REGEX = {"/**/": "/(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
GLOB_STAND_IN = {"/**/": "/any-dir/", "**": "any-dir", "*": "any", "?": "x"}


def parse_rule(rule: str) -> tuple[str, str | None]:
    """Split `Tool(specifier)` into tool and specifier; a bare tool has none."""
    tool, paren, rest = rule.partition("(")
    if paren and rest.endswith(")"):
        return tool, rest[:-1]
    return rule, None


def bash_matches(pattern: str, command: str) -> bool:
    if pattern.endswith(":*"):
        pattern = pattern[:-2] + " *"
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    if re.fullmatch(regex, command, re.DOTALL):
        return True
    # A trailing " *" that is the only wildcard also matches the bare command.
    bare = pattern.endswith(" *") and pattern.count("*") == 1
    return bare and command == pattern[:-2]


def ask_spec(path: str) -> str:
    """The path of a protected path's Edit ask rule: a directory gets `/**`."""
    return f"/{path}**" if path.endswith("/") else f"/{path}"


def ask_rule(path: str) -> str:
    return f"Edit({ask_spec(path)})"


def anchor(spec: str) -> tuple[str, str]:
    """Split a Read/Edit rule path into a literal base directory and a glob."""
    if spec.startswith("//"):
        base, glob = "", spec[1:]
    elif spec.startswith("~/"):
        base, glob = str(Path.home().resolve()), spec[1:]
    elif spec.startswith("/"):
        base, glob = str(REPO_ROOT), spec
    else:
        relative = spec.removeprefix("./")
        # Without a slash (a trailing one aside), a pattern matches at any depth.
        nested = "/" in relative.rstrip("/")
        base, glob = str(REPO_ROOT), ("/" if nested else "/**/") + relative
    if glob.endswith("/"):
        glob += "**"  # a directory covers everything below it
    return base, glob


def token_regex(token: str) -> str:
    if token.startswith("[") and len(token) > 1:
        return "[^" + token[2:] if token.startswith("[!") else token
    return GLOB_REGEX.get(token, re.escape(token))


def token_stand_in(token: str) -> str:
    if token.startswith("[") and len(token) > 1:
        return "x" if token.startswith("[!") else token[1]
    return GLOB_STAND_IN.get(token, token)


def path_matches(spec: str, path: str) -> bool:
    """Whether a rule path matches path or a directory above it (gitignore)."""
    base, glob = anchor(spec)
    regex = re.escape(base) + GLOB_TOKEN.sub(lambda m: token_regex(m.group()), glob)
    candidates = [PurePosixPath(path), *PurePosixPath(path).parents]
    return any(re.fullmatch(regex, str(c), re.DOTALL) for c in candidates)


def stand_in(spec: str) -> str:
    """A path that a rule path matches: each wildcard is filled in with a name."""
    base, glob = anchor(spec)
    return base + GLOB_TOKEN.sub(lambda m: token_stand_in(m.group()), glob)


def files_on_disk(path: str) -> list[str]:
    """The files at a protected path in this checkout."""
    if path.endswith("/"):
        found = (REPO_ROOT / path).rglob("*")
    else:
        found = REPO_ROOT.glob(path)
    return [str(file) for file in found if file.is_file()]


def overlaps(spec: str | None, path: str) -> bool:
    """Whether an allow rule path matches a sample file at the protected path."""
    if spec is None:
        return True  # a tool name without a path matches every file
    protected = ask_spec(path)
    samples = [stand_in(protected), *files_on_disk(path)]
    return any(path_matches(spec, sample) for sample in samples) or path_matches(
        protected, stand_in(spec)
    )


def allow_problems(rule: str) -> list[str]:
    tool, spec = parse_rule(rule)
    if tool == "Bash":
        if spec is None or spec == "*":
            return [f"allow rule {rule} allows every command"]
        return [
            f"allow rule {rule} covers {covered}"
            for covered, commands in SAMPLE_COMMANDS.items()
            if any(bash_matches(spec, command) for command in commands)
        ]
    if tool in FILE_EDIT_TOOLS:
        return [
            f"allow rule {rule} overlaps protected path {path}"
            for path in PROTECTED_PATHS
            if overlaps(spec, path)
        ]
    return []


def policy_problems(settings: Settings, gitignore: str) -> list[str]:
    permissions = settings.get("permissions", {})
    allow, ask, deny = (permissions.get(kind, []) for kind in ("allow", "ask", "deny"))

    problems = [
        f"no deny rule {rule}"
        for rule in [*MUST_DENY_BASH, *MUST_DENY_READ]
        if rule not in deny
    ]
    problems += [
        f"no ask or deny rule {rule}"
        for rule in MUST_ASK_OR_DENY
        if rule not in ask + deny
    ]
    problems += [
        f"no ask rule {ask_rule(path)} for protected path {path}"
        for path in PROTECTED_PATHS
        if ask_rule(path) not in ask
    ]
    for rule in allow:
        problems += allow_problems(rule)
    if permissions.get("defaultMode") == "bypassPermissions":
        problems.append("defaultMode is bypassPermissions")
    if LOCAL_SETTINGS not in [line.strip() for line in gitignore.splitlines()]:
        problems.append(f".gitignore does not list {LOCAL_SETTINGS}")
    return problems


def move(rule: str, source: str | None, target: str | None) -> Mutation:
    """Move rule from one permission list to another; None drops or adds it."""

    def mutate(settings: Settings, gitignore: list[str]) -> None:
        permissions = settings["permissions"]
        if source is not None:
            permissions[source].remove(rule)  # raises if the rule is not there
        if target is not None:
            permissions.setdefault(target, []).append(rule)

    return mutate


def bypass_permissions(settings: Settings, gitignore: list[str]) -> None:
    settings["permissions"]["defaultMode"] = "bypassPermissions"


def unignore_local_settings(settings: Settings, gitignore: list[str]) -> None:
    gitignore.remove(LOCAL_SETTINGS)


# Each mutation of the real files, with exactly the problems it must cause.
MUTATIONS: dict[str, tuple[Mutation, list[str]]] = {
    "gh pr merge moved to allow": (
        move("Bash(gh pr merge *)", "deny", "allow"),
        [
            "no deny rule Bash(gh pr merge *)",
            "allow rule Bash(gh pr merge *) covers Bash(gh pr merge *)",
        ],
    ),
    "curl deny dropped": (
        move("Bash(curl *)", "deny", None),
        ["no deny rule Bash(curl *)"],
    ),
    "gh auth token deny dropped": (
        move("Bash(gh auth token*)", "deny", None),
        ["no deny rule Bash(gh auth token*)"],
    ),
    "set-rulesets.sh --apply deny dropped": (
        move("Bash(*set-rulesets.sh*--apply*)", "deny", None),
        ["no deny rule Bash(*set-rulesets.sh*--apply*)"],
    ),
    "docker ask dropped": (
        move("Bash(docker *)", "ask", None),
        ["no ask or deny rule Bash(docker *)"],
    ),
    "AGENTS.md ask rule dropped": (
        move("Edit(/AGENTS.md)", "ask", None),
        ["no ask rule Edit(/AGENTS.md) for protected path AGENTS.md"],
    ),
    ".github edit rule added to allow": (
        move("Edit(/.github/**)", None, "allow"),
        ["allow rule Edit(/.github/**) overlaps protected path .github/"],
    ),
    "Bash(*) added to allow": (
        move("Bash(*)", None, "allow"),
        ["allow rule Bash(*) allows every command"],
    ),
    "bare Bash added to allow": (
        move("Bash", None, "allow"),
        ["allow rule Bash allows every command"],
    ),
    "defaultMode bypassPermissions": (
        bypass_permissions,
        ["defaultMode is bypassPermissions"],
    ),
    "settings.local.json line removed from .gitignore": (
        unignore_local_settings,
        [".gitignore does not list .claude/settings.local.json"],
    ),
}


def overlap_problems(rule: str, *paths: str) -> list[str]:
    return [f"allow rule {rule} overlaps protected path {path}" for path in paths]


# Allow rules, each with exactly the problems it causes.
ALLOW_RULES: dict[str, list[str]] = {
    "Bash(git status)": [],
    "Bash(gh pr view *)": [],
    "Bash(git push *)": [
        "allow rule Bash(git push *) covers Bash(git push --force*)",
        "allow rule Bash(git push *) covers Bash(git push * --force*)",
        "allow rule Bash(git push *) covers Bash(git push *)",
    ],
    "Bash(gh pr *)": [
        "allow rule Bash(gh pr *) covers Bash(gh pr merge *)",
        "allow rule Bash(gh pr *) covers Bash(gh pr create *)",
    ],
    "Bash(docker *)": ["allow rule Bash(docker *) covers Bash(docker *)"],
    "Bash(sudo:*)": ["allow rule Bash(sudo:*) covers Bash(sudo *)"],
    "Edit(/src/**)": [],
    "Edit(/README.md)": [],
    "Edit": overlap_problems("Edit", *PROTECTED_PATHS),
    "Write": overlap_problems("Write", *PROTECTED_PATHS),
    "Edit(**)": overlap_problems("Edit(**)", *PROTECTED_PATHS),
    "Edit(//**)": overlap_problems("Edit(//**)", *PROTECTED_PATHS),
    "Edit(CLAUDE.md)": overlap_problems("Edit(CLAUDE.md)", "CLAUDE.md"),
    "Edit(/.github/workflows/**)": overlap_problems(
        "Edit(/.github/workflows/**)", ".github/"
    ),
    "Edit(/.github/CODEOWNERS)": overlap_problems(
        "Edit(/.github/CODEOWNERS)", ".github/"
    ),
    "Edit(/[.]github/**)": overlap_problems("Edit(/[.]github/**)", ".github/"),
    "Edit(**/ci.yml)": overlap_problems("Edit(**/ci.yml)", ".github/"),
    "Edit(/docs/**)": overlap_problems("Edit(/docs/**)", "docs/adr/"),
    "Edit(/images/base/Dockerfile)": overlap_problems(
        "Edit(/images/base/Dockerfile)", "images/**/Dockerfile"
    ),
}

# (pattern, command, matches) rows from the wildcard table in the permissions docs.
BASH_EXAMPLES = [
    ("npm run build", "npm run build", True),
    ("npm run build", "npm run build --watch", False),
    ("npm run *", "npm run", True),
    ("npm run *", "npm install", False),
    ("git log * main", "git log --oneline main", True),
    ("git log * main", "git log main", False),
    ("git * main", "git push origin main", True),
    ("ls *", "ls", True),
    ("ls *", "ls -la", True),
    ("ls *", "lsof", False),
    ("ls*", "lsof", True),
    ("* --help *", "npm --help x", True),
    ("* --help *", "npm --help", False),
    ("ls:*", "ls", True),
]
# (allow rule path, path below the repository root, matches) from the Read and
# Edit section of the permissions docs.
PATH_EXAMPLES = [
    ("/src/**", "src/app.ts", True),
    ("/src/**", "vendor/pkg/src/lib.js", False),
    ("src/**", "src/app.ts", True),
    ("src/**", "vendor/pkg/src/lib.js", False),
    ("**/src/**", "vendor/pkg/src/lib.js", True),
    (".env", "config/.env", True),
]


def load_settings() -> Settings:
    return json.loads(SETTINGS.read_text())


def test_repo_settings_follow_policy() -> None:
    assert policy_problems(load_settings(), GITIGNORE.read_text()) == []


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(name: str) -> None:
    mutate, problems = MUTATIONS[name]
    settings, gitignore = load_settings(), GITIGNORE.read_text().splitlines()
    mutate(settings, gitignore)

    unchanged = (load_settings(), GITIGNORE.read_text().splitlines())
    assert (settings, gitignore) != unchanged  # the mutation really changed something
    assert policy_problems(settings, "\n".join(gitignore)) == problems


def test_check_accepts_ask_rule_moved_to_deny() -> None:
    settings = load_settings()
    move("Bash(docker *)", "ask", "deny")(settings, [])

    assert policy_problems(settings, GITIGNORE.read_text()) == []


@pytest.mark.parametrize("rule", ALLOW_RULES)
def test_check_reports_allow_rule(rule: str) -> None:
    assert allow_problems(rule) == ALLOW_RULES[rule]


@pytest.mark.parametrize("rule", SAMPLE_COMMANDS)
def test_sample_commands_match_their_rule(rule: str) -> None:
    tool, spec = parse_rule(rule)

    assert tool == "Bash"
    assert spec is not None
    for command in SAMPLE_COMMANDS[rule]:
        assert bash_matches(spec, command), command


@pytest.mark.parametrize(("pattern", "command", "expected"), BASH_EXAMPLES)
def test_bash_matching_follows_docs(pattern: str, command: str, expected: bool) -> None:
    assert bash_matches(pattern, command) is expected


@pytest.mark.parametrize(("spec", "path", "expected"), PATH_EXAMPLES)
def test_path_matching_follows_docs(spec: str, path: str, expected: bool) -> None:
    assert path_matches(spec, str(REPO_ROOT / path)) is expected
