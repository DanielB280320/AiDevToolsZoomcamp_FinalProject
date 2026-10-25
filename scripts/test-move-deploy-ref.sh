#!/usr/bin/env bash
# Tests scripts/move-deploy-ref.sh against a fake `gh` that models the GitHub rule: a ref update
# whose new tree differs from the old ref's tree in .github/workflows/ is a 403.
# Issue #14 (defect: promoting a SHA whose workflows differ from deploy/prod failed with 403).
# Model: the old ref has tree "tree-old-wf"; the release commit has tree "tree-rel-wf" (different
# workflows). Any commit whose tree is not "tree-old-wf" and not "tree-readme" is a workflow change.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state"
S="$tmp/state"
REL=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
H=$(printf '1%.0s' $(seq 40)); D=$(printf '2%.0s' $(seq 64))
B="ghcr.io/o/fitwise-backend@sha256:$D"; F="ghcr.io/o/fitwise-frontend@sha256:$D"
cat > "$tmp/bin/gh" <<'FAKE'
#!/usr/bin/env bash
S="$FAKE_STATE"; a="$*"
case "$a" in
  *"git/ref/heads/deploy/"*)
     if [ -f "$S/ref" ]; then cat "$S/ref"
     else echo "gh: ${FAKE_READ_ERR:-Not Found (HTTP 404)}" >&2; exit 1; fi ;;
  *"git/commits/$FAKE_HEAD"*) echo tree-old-wf ;;
  *"git/commits/$FAKE_REL"*) echo tree-rel-wf ;;
  *"git/trees"*) cat >/dev/null; echo tree-readme ;;
  *"-X PATCH"*)
     t="$(cat "$S/last_tree")"
     if [ "$t" != tree-old-wf ] && [ "$t" != tree-readme ]; then
       echo "gh: Resource not accessible by integration (HTTP 403)" >&2; exit 1
     fi
     echo moved > "$S/moved" ;;
  *"-X POST"*) echo created > "$S/created" ;;
  *"git/commits"*)
     for x in "$@"; do case "$x" in
       tree=*) echo "${x#tree=}" > "$S/last_tree" ;;
       parents*) echo "$x" > "$S/last_parent" ;;
       message=*) echo "$x" > "$S/last_msg" ;;
     esac; done
     echo newcommit0000000000000000000000000000000 ;;
  *) echo "unexpected gh call: $a" >&2; exit 1 ;;
esac
FAKE
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" GITHUB_REPOSITORY=o/r FAKE_STATE="$S" FAKE_HEAD="$H" FAKE_REL="$REL"
fails=0
ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fails=$((fails+1)); }

# 1. Existing ref, release with different workflows: succeeds, tree reused, parent = old head.
rm -f "$S"/*; echo "$H" > "$S/ref"
out="$("$here/move-deploy-ref.sh" prod "$REL" "$B" "$F" 2>/dev/null)"; rc=$?
if [ "$rc" = 0 ] && [ -f "$S/moved" ]; then ok "release with different workflows: ref moved (no 403)"; else bad "different workflows: rc=$rc"; fi
if [ "$(cat "$S/last_tree")" = tree-old-wf ]; then ok "deploy commit tree = current ref tree (no .github/workflows diff)"; else bad "tree is $(cat "$S/last_tree")"; fi
if grep -q "parents\[\]=$H" "$S/last_parent"; then ok "parent = current ref head"; else bad "parent"; fi
if grep -q "source: $REL" "$S/last_msg" && grep -q "backend: $B" "$S/last_msg" && grep -q "frontend: $F" "$S/last_msg"; then ok "release record in message"; else bad "message"; fi
if [ "$out" = newcommit0000000000000000000000000000000 ]; then ok "prints the new commit sha"; else bad "stdout: $out"; fi

# 2. Guard: the fake rejects the old behaviour (release tree), proving the test can fail.
echo tree-rel-wf > "$S/last_tree"
if gh api -X PATCH x 2>/dev/null; then bad "fake accepted a workflow change"; else ok "fake rejects a release-tree commit like GitHub does"; fi

# 3. First deploy (no ref): README-only tree, no parent, ref created.
rm -f "$S"/*
"$here/move-deploy-ref.sh" dev "$REL" "$B" "$F" >/dev/null 2>&1
if [ -f "$S/created" ] && [ "$(cat "$S/last_tree")" = tree-readme ] && [ ! -f "$S/last_parent" ]; then ok "first deploy: README-only tree, no parent, ref created"; else bad "first deploy"; fi

# 3b. Reading the ref fails with something other than 404: exit non-zero, real status shown, no write.
for e in "Internal Server Error (HTTP 500)" "Resource not accessible by integration (HTTP 403)" "dial tcp: lookup api.github.com: no such host"; do
  rm -f "$S"/*
  msg="$(FAKE_READ_ERR="$e" "$here/move-deploy-ref.sh" dev "$REL" "$B" "$F" 2>&1 >/dev/null)"; rc=$?
  if [ "$rc" != 0 ] && [ ! -f "$S/created" ] && [ ! -f "$S/moved" ] && [ ! -f "$S/last_tree" ] && [[ "$msg" == *"$e"* ]]; then ok "read error '${e: -10}': fails, shows cause, no write"; else bad "read error '$e': rc=$rc msg=$msg"; fi
done

# 4. Input validation.
"$here/move-deploy-ref.sh" staging "$REL" "$B" "$F" >/dev/null 2>&1; if [ $? = 2 ]; then ok "rejects unknown env"; else bad "env"; fi
"$here/move-deploy-ref.sh" prod abc "$B" "$F" >/dev/null 2>&1; if [ $? = 2 ]; then ok "rejects short sha"; else bad "sha"; fi

if [ "$fails" = 0 ]; then echo "all move-deploy-ref tests passed"; else echo "$fails failed"; exit 1; fi
