#!/usr/bin/env bash
# Move the ref deploy/<env> to a new "deploy commit" for a release (issues #13, #14; ADR 0010).
#   GITHUB_REPOSITORY=<owner/repo> GH_TOKEN=... scripts/move-deploy-ref.sh <dev|prod> <40-hex sha> <backend image> <frontend image>
# Prints the new deploy commit SHA on stdout (progress goes to stderr).
#
# What the host reads from the deploy commit: only its SHA and its message (the release record:
# source / backend / frontend). deploy.sh fetches the compose files of the release from the SOURCE
# sha, never from the deploy commit's tree. So the tree is irrelevant to the host, and it must not
# change any file under .github/workflows/: GITHUB_TOKEN can never get the `workflows` permission,
# and a ref update that changes workflow files is rejected with HTTP 403.
# Therefore the deploy commit REUSES THE TREE OF THE CURRENT deploy/<env> COMMIT (zero diff, so
# promoting an old release, a rollback, or a release that edits workflows all work), with the
# current commit as parent (linear, auditable history). The very first commit gets a tree with a
# single README and no .github/.
set -euo pipefail

env_name="${1:?env (dev|prod)}"; sha="${2:?release sha}"; backend="${3:?backend image}"; frontend="${4:?frontend image}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
[[ "$env_name" =~ ^(dev|prod)$ ]] || { echo "env must be dev or prod" >&2; exit 2; }
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "sha must be 40 lowercase hex characters" >&2; exit 2; }

ref="deploy/$env_name"
msg="$(printf 'deploy %s %s\n\nsource: %s\nbackend: %s\nfrontend: %s\n' "$env_name" "$sha" "$sha" "$backend" "$frontend")"

if head="$(gh api "repos/$repo/git/ref/heads/$ref" --jq .object.sha 2>/dev/null)" && [ -n "$head" ]; then
  tree="$(gh api "repos/$repo/git/commits/$head" --jq .tree.sha)"
  new="$(gh api "repos/$repo/git/commits" -f message="$msg" -f tree="$tree" -f "parents[]=$head" --jq .sha)"
  gh api -X PATCH "repos/$repo/git/refs/heads/$ref" -f sha="$new" -F force=true >/dev/null
else
  tree="$(printf '%s' '{"tree":[{"path":"README.md","mode":"100644","type":"blob","content":"Release records for the pull-based deploy (ADR 0010). Only the commit message matters; this tree holds no code and no .github/.\n"}]}' |
    gh api "repos/$repo/git/trees" --input - --jq .sha)"
  new="$(gh api "repos/$repo/git/commits" -f message="$msg" -f tree="$tree" --jq .sha)"
  gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$ref" -f sha="$new" >/dev/null
fi
echo "$ref -> $new (release $sha)" >&2
echo "$new"
