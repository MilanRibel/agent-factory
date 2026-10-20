# agent-factory
Local, containerised agent factory for autonomous ML engineering

## Working with Claude Code
Start Claude Code in Manual (`default`) or plan mode; without the flag, a terminal
session starts in `auto` in Claude Code 2.1.303:

```sh
claude --permission-mode default
claude --permission-mode plan
```

Never switch to `acceptEdits` or `auto`; Shift+Tab cycles through both, so stop only
on Manual or plan. Answer each permission prompt with `Yes` or `No` for that one
call; never pick an option that accepts edits automatically, doesn't ask again or
switches to auto mode. The ask rules in `.claude/settings.json` cover only the
`Edit` tool, so in `acceptEdits` a Bash command can change a protected file without
asking you. The full rules are in [AGENTS.md](AGENTS.md#permission-mode).

## Pre-commit hooks
`.pre-commit-config.yaml` runs ruff (check and format), gitleaks and a few file
checks before each commit. Install the hooks once per checkout:

```sh
uv run pre-commit install
uv run pre-commit run --all-files   # optional: check every file now
```

The hooks are a convenience: they run only where someone installed them, and
`git commit --no-verify` skips them. CI is the gate. The gitleaks hook builds
gitleaks from source on the pinned rev, so it needs Go on `PATH`. The first run
fetches the hook repositories from GitHub and their packages from PyPI.

## Branch protection
`scripts/set-rulesets.sh` protects the default branch (`main`) with the GitHub
ruleset `protect-main`:
- deleting the branch and force pushes are blocked;
- every change goes through a pull request (0 required approvals in phase 0, since
  the only account is also the PR author; phase 4 raises this to 1 approval plus
  code-owner review);
- the status checks `lint`, `test`, `secret-scan` and `workflow-lint` must pass, on
  a branch that is up to date with `main`;
- nobody can bypass the ruleset.

A human runs this script, never an agent. Run it in your own terminal, not through
Claude Code and not with `!` in Claude Code: `--apply` refuses to run when
`CLAUDECODE` is set.

```sh
scripts/set-rulesets.sh                          # dry run
scripts/set-rulesets.sh --apply                  # create or update the ruleset
scripts/set-rulesets.sh --repo OWNER/NAME        # another repository
```

- The dry run needs no network access and no gh auth. It prints the ruleset JSON on
  stdout, and the target repository and the `gh api` calls `--apply` would make on
  stderr.
- Without `--repo`, the target is the GitHub `origin` remote of this checkout.
- `--apply` needs `gh auth login` with admin rights on the repository. It finds the
  ruleset by name, so running it again updates the same ruleset instead of adding
  one.

Check the result:
1. Settings > Rules > Rulesets shows `protect-main` as Active.
2. A direct push to `main` is rejected:
   ```sh
   git switch main
   git commit --allow-empty -m "test: direct push to main"
   git push origin main        # must be rejected
   git reset --hard origin/main
   ```

The required checks are job names in `.github/workflows/`. A test fails when they
drift apart, so rename a job and its required check in the same PR.

### Rollback
Settings > Rules > Rulesets > `protect-main`: set Enforcement status to Disabled, or
delete the ruleset. Running `--apply` again sets it back to Active.
