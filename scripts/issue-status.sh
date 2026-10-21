#!/usr/bin/env bash
# Move an issue to a workflow status: updates its status:* label and its
# column on the FitWise Backlog project board (see docs/process.md).
#
#   scripts/issue-status.sh <issue> <backlog|ready|in-progress|in-qa|blocked|done>
#
# "blocked" only changes the label (the card stays in its column);
# "done" removes all status labels and moves the card to Done.
set -euo pipefail

OWNER="${FITWISE_PROJECT_OWNER:-DanielB280320}"
PROJECT="${FITWISE_PROJECT_NUMBER:-1}"

issue="${1:?usage: $0 <issue> <status>}"
status="${2:?usage: $0 <issue> <status>}"

case "$status" in
  backlog)     column="Backlog" ;;
  ready)       column="Ready" ;;
  in-progress) column="In progress" ;;
  in-qa)       column="In QA" ;;
  blocked)     column="" ;;
  done)        column="Done" ;;
  *) echo "unknown status: $status" >&2; exit 2 ;;
esac

# Labels: drop every other status:* label, then add the new one.
current=$(gh issue view "$issue" --json labels --jq '.labels[].name | select(startswith("status:"))')
for label in $current; do
  [[ "$label" == "status:$status" ]] || gh issue edit "$issue" --remove-label "$label" >/dev/null
done
if [[ "$status" != "done" ]]; then
  gh issue edit "$issue" --add-label "status:$status" >/dev/null
fi

# Board column.
if [[ -n "$column" ]]; then
  project_id=$(gh project view "$PROJECT" --owner "$OWNER" --format json --jq .id)
  read -r field_id option_id < <(gh project field-list "$PROJECT" --owner "$OWNER" --format json \
    --jq ".fields[] | select(.name==\"Status\") | \"\(.id) \(.options[] | select(.name==\"$column\") | .id)\"")
  item_id=$(gh project item-list "$PROJECT" --owner "$OWNER" --limit 500 --format json \
    --jq ".items[] | select(.content.number==$issue) | .id")
  if [[ -z "$item_id" ]]; then
    url=$(gh issue view "$issue" --json url --jq .url)
    item_id=$(gh project item-add "$PROJECT" --owner "$OWNER" --url "$url" --format json --jq .id)
  fi
  gh project item-edit --id "$item_id" --project-id "$project_id" \
    --field-id "$field_id" --single-select-option-id "$option_id" >/dev/null
fi

echo "#$issue → $status${column:+ ($column)}"
