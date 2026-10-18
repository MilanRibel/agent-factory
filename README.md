# agent-factory
Local, containerised agent factory for autonomous ML engineering

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
