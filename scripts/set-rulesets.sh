#!/usr/bin/env bash
# Protect the default branch with the GitHub ruleset "protect-main".
#
# A human runs this, never an agent (docs/spec.md). The protection that counts in
# phase 0 is the permission prompt: `Bash(gh api *)` is an ask rule in
# .claude/settings.json and this script is not in the allow list, so even starting
# it needs approval. The CLAUDECODE guard below and the deny rule for
# `set-rulesets.sh --apply` are tripwires, not a security boundary. The real
# boundary (agent identities without admin rights) comes in phase 4, together with
# 1 required approval and code-owner review.
#
# Without --apply this is a dry run: the ruleset JSON goes to stdout, the target
# repository and the gh api calls --apply would make go to stderr, and gh is not
# called. Keep this file bash 3.2 compatible (macOS /bin/bash).
set -euo pipefail

# Byte-wise character ranges in the repository name check.
export LC_ALL=C

readonly RULESET_NAME="protect-main"
readonly LIST_JQ='.[] | [.id, .name] | @tsv'

usage() {
  cat <<'EOF'
Usage: scripts/set-rulesets.sh [--apply] [--repo OWNER/NAME]

Protect the default branch with the GitHub ruleset "protect-main".

Without --apply this is a dry run: it prints the ruleset JSON on stdout and the
gh api calls --apply would make on stderr. Nothing is sent.

Options:
  --apply            create or update the ruleset (needs gh auth with admin rights)
  --repo OWNER/NAME  target repository (default: the GitHub origin remote of the
                     checkout this script is in)
  -h, --help         show this help
EOF
}

die() {
  echo "set-rulesets.sh: $1" >&2
  exit "${2:-1}"
}

usage_error() {
  echo "set-rulesets.sh: $1" >&2
  usage >&2
  exit 2
}

# OWNER/NAME only, so the value cannot add path segments or a query to an endpoint.
valid_repo() {
  local pattern='^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$'
  [[ $1 =~ $pattern ]] || return 1
  case "${1#*/}" in
    . | ..) return 1 ;;
  esac
}

# OWNER/NAME from the origin remote of this script's checkout; local, no network.
repo_from_origin() {
  local script_dir url
  script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  url=$(git -C "$script_dir" remote get-url origin 2>/dev/null) || return 1
  url=${url%.git}
  case "$url" in
    https://github.com/*) echo "${url#https://github.com/}" ;;
    git@github.com:*) echo "${url#git@github.com:}" ;;
    ssh://git@github.com/*) echo "${url#ssh://git@github.com/}" ;;
    *) return 1 ;;
  esac
}

# bypass_actors is explicit: a PUT without it keeps bypass actors added in the UI.
# The required checks must equal the job names in .github/workflows (tested).
ruleset_json() {
  cat <<EOF
{
  "name": "${RULESET_NAME}",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          {"context": "lint"},
          {"context": "test"},
          {"context": "secret-scan"},
          {"context": "workflow-lint"}
        ]
      }
    }
  ]
}
EOF
}

apply=false
repo=""
repo_given=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --repo)
      [ "$#" -ge 2 ] || usage_error "--repo needs a value"
      repo=$2
      repo_given=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) usage_error "unknown argument: $1" ;;
  esac
  shift
done

# Claude Code sets CLAUDECODE in its shells; an empty value counts as set.
if [ "$apply" = true ] && [ -n "${CLAUDECODE+set}" ]; then
  die "refusing --apply: CLAUDECODE is set, so this is a Claude Code shell; run it in your own terminal"
fi

if [ "$repo_given" = true ]; then
  valid_repo "$repo" || die "invalid --repo value '$repo': expected OWNER/NAME" 2
elif ! repo=$(repo_from_origin) || ! valid_repo "$repo"; then
  die "cannot derive the repository from the origin remote; pass --repo OWNER/NAME" 2
fi

echo "Target repository: $repo" >&2
listing_endpoint="repos/$repo/rulesets?includes_parents=false"

if [ "$apply" = false ]; then
  {
    echo "Dry run, nothing is sent. --apply would run:"
    echo "  gh api '$listing_endpoint' --paginate --jq '$LIST_JQ'"
    echo "  then, if no ruleset is named $RULESET_NAME:"
    echo "    gh api repos/$repo/rulesets --method POST --input -"
    echo "  or, if one is:"
    echo "    gh api repos/$repo/rulesets/<id> --method PUT --input -"
    echo "  with the ruleset JSON on stdout as input."
  } >&2
  ruleset_json
  exit 0
fi

# An assignment, so a failing gh stops the script (set -e) before any write.
listing=$(gh api "$listing_endpoint" --paginate --jq "$LIST_JQ")

match_ids=""
match_count=0
while IFS=$'\t' read -r ruleset_id ruleset_name; do
  if [ "$ruleset_name" = "$RULESET_NAME" ]; then
    case "$ruleset_id" in
      '' | *[!0-9]*) die "unexpected ruleset id '$ruleset_id' in the listing" ;;
    esac
    match_ids="$match_ids $ruleset_id"
    match_count=$((match_count + 1))
  fi
done <<<"$listing"

case "$match_count" in
  0)
    echo "Creating ruleset $RULESET_NAME in $repo" >&2
    ruleset_json | gh api "repos/$repo/rulesets" --method POST --input -
    ;;
  1)
    ruleset_id=${match_ids# }
    echo "Updating ruleset $RULESET_NAME (id $ruleset_id) in $repo" >&2
    ruleset_json | gh api "repos/$repo/rulesets/$ruleset_id" --method PUT --input -
    ;;
  *)
    die "found $match_count rulesets named $RULESET_NAME (ids:$match_ids) in $repo; remove the extra ones in Settings > Rules > Rulesets first"
    ;;
esac
