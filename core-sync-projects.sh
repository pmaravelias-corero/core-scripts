#!/usr/bin/env bash
# core-sync-projects — fetch, checkout main, and prune all projects
#
# Install:
#   chmod +x ~/Projects/core-scripts/core-sync-projects.sh
#   sudo ln -s ~/Projects/core-scripts/core-sync-projects.sh /usr/local/bin/core-sync-projects

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PROJECTS_DIR="${PROJECTS_DIR:-$HOME/Projects}"

PROJECTS=(
  corelet-shell
  corelet-ta
  corelet-ztac
  corelet-auth-mgmt
  corelet-common
  corelet-chassis
)

# ── Colors ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
  CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
fi

# ── Logging helpers ───────────────────────────────────────────────────────────
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✘${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }

# ── Git wrapper ───────────────────────────────────────────────────────────────
# Runs a git command, prints result, returns its exit code.
run_git() {
  local output
  if output=$(git "$@" 2>&1); then
    ok "git $*"
    return 0
  else
    local exit_code=$?
    err "git $* (exit $exit_code)"
    [[ -n "$output" ]] && echo -e "     ${RED}${output}${RESET}"
    return $exit_code
  fi
}

# ── Prompt helper ─────────────────────────────────────────────────────────────
# prompt_choice QUESTION OPTION…
# Each OPTION is a "key:Label" pair, e.g. "c:Continue" "s:Stash" "a:Abort".
# Renders:  [c] Continue, [s] Stash, [a] Abort
# Reads a single keypress and echoes the chosen key (lowercase).
prompt_choice() {
  local question="$1"; shift
  local options=("$@")
  local display_parts=() key label part
  local reply

  for opt in "${options[@]}"; do
    key="${opt%%:*}"
    label="${opt#*:}"
    display_parts+=("[${key}] ${label}")
  done

  local display_str
  display_str=$(IFS=', '; echo "${display_parts[*]}")
  echo -e "\n  ${YELLOW}?${RESET}  ${question}\n     ${display_str} " >&2
  read -r -n 1 reply </dev/tty
  echo >&2   # newline after keypress
  echo "${reply,,}"  # return lowercase key
}

# ── Per-project steps ─────────────────────────────────────────────────────────

# Check the project directory exists.
check_dir() {
  local proj_dir="$1" proj="$2"
  if [[ ! -d "$proj_dir" ]]; then
    warn "Directory not found, skipping"
    return 2
  fi
}

# Check the directory is a git repository.
check_git_repo() {
  local proj_dir="$1"
  if ! git -C "$proj_dir" rev-parse --git-dir &>/dev/null; then
    warn "Not a git repository, skipping"
    return 2
  fi
}

# Detect uncommitted changes (staged or unstaged).
# Prints "true" if dirty, "false" otherwise.
detect_dirty() {
  local proj_dir="$1"
  if ! git -C "$proj_dir" diff --quiet || \
     ! git -C "$proj_dir" diff --cached --quiet; then
    echo "true"
  else
    echo "false"
  fi
}

# Determine the remote default branch (falls back to "main").
get_default_branch() {
  local proj_dir="$1"
  git -C "$proj_dir" remote show origin 2>/dev/null \
    | awk '/HEAD branch/ {print $NF}' \
    || echo "main"
}

# Fetch and prune remote refs.
do_fetch() {
  run_git fetch --prune || true
}

# Stash, checkout + reset to origin/<branch>, then restore stash if one was made.
# Exit codes: 0 success, 1 error (stash failed), 2 aborted by user.
do_checkout() {
  local default_branch="$1" dirty="$2"
  local stashed=false

  if [[ "$dirty" == "true" ]]; then
    warn "Uncommitted changes detected"
    local choice
    choice=$(prompt_choice \
      "How should we handle uncommitted changes before checkout?" \
      "c:Continue" "s:Stash & Re-apply" "a:Abort")

    case "$choice" in
      c)
        info "Continuing without touching working tree" ;;
      s)
        info "Stashing changes..."
        run_git stash push -m "update-projects auto-stash" || {
          err "Stash failed — aborting checkout"
          return 1
        }
        stashed=true
        ;;
      a)
        warn "Aborted by user"
        return 2
        ;;
      *)
        warn "Unrecognised choice '${choice}' — aborting"
        return 2
        ;;
    esac
  fi

  run_git checkout "$default_branch" || true
  run_git reset --hard "origin/$default_branch" || true

  if [[ "$stashed" == true ]]; then
    info "Restoring stash..."
    run_git stash pop || warn "Stash pop failed — your stash is still saved (git stash list)"
  fi
}

# Prune remote-tracking refs for origin.
prune_remote_refs() {
  info "Pruning remote refs..."
  git remote prune origin 2>&1 | sed "s/^/     /" || true
  ok "Remote refs pruned"
}

# Delete local branches fully merged into HEAD (except trunk branches).
prune_merged_branches() {
  info "Pruning merged local branches..."
  local merged
  merged=$(git branch --merged HEAD \
    | grep -vE '^\*|^\s*(main|master|develop|dev)$' || true)

  if [[ -z "$merged" ]]; then
    ok "No merged branches to prune"
    return
  fi

  while IFS= read -r branch; do
    branch="${branch// /}"
    run_git branch -d "$branch" || warn "Could not delete: $branch"
  done <<< "$merged"
  ok "Merged branches pruned"
}

# Orchestrate all steps for a single project.
# Returns non-zero if any required step fails.
process_project() {
  local proj="$1"
  local proj_dir="$PROJECTS_DIR/$proj"

  check_dir    "$proj_dir" "$proj" || return $?
  check_git_repo "$proj_dir"       || return $?

  local dirty default_branch
  dirty=$(detect_dirty "$proj_dir")

  (
    cd "$proj_dir"

    default_branch=$(get_default_branch "$proj_dir")
    info "Default branch: $default_branch"

    do_fetch

    local checkout_rc=0
    do_checkout "$default_branch" "$dirty" || checkout_rc=$?

    if (( checkout_rc == 2 )); then
      return 0   # aborted by user — not a failure, but skip pruning
    elif (( checkout_rc != 0 )); then
      return $checkout_rc
    fi

    prune_remote_refs
    prune_merged_branches
  )
}

# ── Main ──────────────────────────────────────────────────────────────────────
declare -a FAILED=()
declare -a SKIPPED=()
declare -a OK=()

echo
echo -e "${BOLD}Updating ${#PROJECTS[@]} projects in ${PROJECTS_DIR}${RESET}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')"
echo

for PROJ in "${PROJECTS[@]}"; do
  echo -e "${BOLD}── $PROJ ${RESET}"

  _rc=0
  process_project "$PROJ" || _rc=$?
  if (( _rc == 0 )); then
    OK+=("$PROJ")
  elif (( _rc == 2 )); then
    SKIPPED+=("$PROJ")
  else
    FAILED+=("$PROJ")
  fi

  echo
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}── Summary ───────────────────────────────────────────${RESET}"
echo -e "  ${GREEN}✔  OK      ${RESET}: ${#OK[@]}  (${OK[*]:-none})"
(( ${#SKIPPED[@]} > 0 )) && echo -e "  ${YELLOW}⚠  Skipped ${RESET}: ${#SKIPPED[@]}  (${SKIPPED[*]})"
(( ${#FAILED[@]}  > 0 )) && echo -e "  ${RED}✘  Failed  ${RESET}: ${#FAILED[@]}  (${FAILED[*]})"
echo

if (( ${#FAILED[@]} > 0 )); then
  exit 1
fi
