#!/usr/bin/env bash
# core-local-deploy — start a CORElet project locally
# Usage: core-local-deploy <corelet-name> [--teardown|--redeploy]
#
# Install:
#   chmod +x ~/Projects/core-local-deploy.sh
#   sudo ln -s ~/Projects/core-local-deploy.sh /usr/local/bin/core-local-deploy
#   echo 'source /usr/local/bin/core-local-deploy' >> ~/.bashrc  # or ~/.zshrc

# ── known CORElets ────────────────────────────────────────────────────────────

CORELETS=(
  corelet-ta
  corelet-ztac
  corelet-auth-mgmt
  corelet-tenant-provisioning
)

# ── shell completion (sourced once by .bashrc / .zshrc) ───────────────────────

if [[ "${BASH_SOURCE[0]:-}" != "$0" ]] || [[ "${ZSH_EVAL_CONTEXT:-}" == *:file* ]]; then
  if [[ -n "${ZSH_VERSION:-}" ]]; then
    _core_local_deploy_complete() {
      if (( CURRENT == 2 )); then compadd "$@" -- $CORELETS
      elif (( CURRENT == 3 )); then compadd "$@" -- --teardown --redeploy
      fi
    }
    compdef _core_local_deploy_complete core-local-deploy
  else
    _core_local_deploy_complete() {
      local cur="${COMP_WORDS[COMP_CWORD]}"
      if [[ COMP_CWORD -eq 1 ]]; then COMPREPLY=( $(compgen -W "${CORELETS[*]}" -- "$cur") )
      elif [[ COMP_CWORD -eq 2 ]]; then COMPREPLY=( $(compgen -W "--teardown --redeploy" -- "$cur") )
      fi
    }
    complete -F _core_local_deploy_complete core-local-deploy
  fi
  return 0
fi

# ── strict mode ───────────────────────────────────────────────────────────────

set -euo pipefail

# ── helpers ───────────────────────────────────────────────────────────────────

die()  { echo "❌  $*" >&2; exit 1; }
info() { echo "▶  $*"; }
ok()   { echo "✅  $*"; }

# ── args & roots ──────────────────────────────────────────────────────────────

CORELET="${1:-}"
[[ -n "$CORELET" ]] || die "Usage: core-local-deploy <corelet-name> [--teardown|--redeploy]  (must match the repo name)"

TEARDOWN=false
REDEPLOY=false
case "${2:-}" in
  --teardown) TEARDOWN=true ;;
  --redeploy) REDEPLOY=true ;;
esac

CORELET_ROOT=~/Projects/$CORELET
[[ -d "$CORELET_ROOT" ]] || die "Could not find CORElet project root: $CORELET_ROOT"

IMAGES_DIR="$CORELET_ROOT/images"
UI_DIR="$IMAGES_DIR/${CORELET}-ui"
API_DIR="$IMAGES_DIR/${CORELET}-api"

# ── teardown ──────────────────────────────────────────────────────────────────

do_teardown() {
  info "Tearing down $CORELET…"
  echo

  info "Stopping dev servers…"
  pids=$(pgrep -f "$IMAGES_DIR" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill 2>/dev/null && ok "Dev server processes killed" || info "Some processes could not be killed (may have already exited)"
  else
    info "No dev server processes found under $IMAGES_DIR"
  fi
  rm -f /tmp/core-local-deploy/${CORELET}-*.log
  ok "Log files removed"

  echo
  info "Bringing down Docker services…"
  pushd "$CORELET_ROOT" > /dev/null
  docker compose --env-file .env.local.docker -f docker-compose.dev.yml down
  popd > /dev/null
  ok "Docker services down"

  echo
  ok "Teardown complete for $CORELET."
}

if $TEARDOWN; then
  do_teardown
  exit 0
fi

if $REDEPLOY; then
  do_teardown
  echo
  info "Redeploying $CORELET…"
  echo
fi

# ── sanity checks ─────────────────────────────────────────────────────────────

[[ -f "$CORELET_ROOT/.env.local.docker"      ]] || die "Missing env file: $CORELET_ROOT/.env.local.docker"
[[ -f "$CORELET_ROOT/docker-compose.dev.yml" ]] || die "Missing compose file: $CORELET_ROOT/docker-compose.dev.yml"
[[ -d "$UI_DIR"                              ]] || die "Missing UI image dir: $UI_DIR"
[[ -d "$API_DIR"                             ]] || die "Missing API image dir: $API_DIR"

bash -c "set -a; source $(printf '%q' "$CORELET_ROOT/.env.local.docker"); set +a" 2>/dev/null \
  || die "Env file failed to source: $CORELET_ROOT/.env.local.docker (check for syntax errors)"

# ── discover optional services ────────────────────────────────────────────────

EXTRA_SERVICES=()
while IFS= read -r -d '' svc_dir; do
  name="$(basename "$svc_dir")"
  [[ "$name" == "${CORELET}-ui"  ]] && continue
  [[ "$name" == "${CORELET}-api" ]] && continue
  EXTRA_SERVICES+=("$svc_dir")
done < <(find "$IMAGES_DIR" -maxdepth 1 -type d -name "${CORELET}-*" -print0 | sort -z)

# ── step 1: docker compose ────────────────────────────────────────────────────

info "Starting Docker services…"
pushd "$CORELET_ROOT" > /dev/null
docker compose --env-file .env.local.docker -f docker-compose.dev.yml up -d
popd > /dev/null
ok "Docker services up"
echo

# ── step 2: terminal launcher ─────────────────────────────────────────────────

BG_PIDS=()
BG_NAMES=()

open_term() {
  local title="$1"; shift
  local dir="$1";  shift
  local cmd="$*"

  local shell_cmd="cd $(printf '%q' "$dir") && $cmd; echo; echo '--- process exited (press Enter to close) ---'; read"

  if command -v kitty &>/dev/null; then
    kitty --title "$title" bash -c "$shell_cmd" &
  elif command -v wezterm &>/dev/null; then
    wezterm start --cwd "$dir" -- bash -c "$shell_cmd" &
  elif command -v gnome-terminal &>/dev/null; then
    gnome-terminal --title="$title" -- bash -c "$shell_cmd" &
  elif command -v x-terminal-emulator &>/dev/null; then
    x-terminal-emulator -T "$title" -e bash -c "$shell_cmd" &
  elif command -v osascript &>/dev/null; then
    osascript -e "
      tell application \"Terminal\"
        do script \"cd $(printf '%q' "$dir") && $cmd\"
        set custom title of front window to \"$title\"
        activate
      end tell"
  else
    local log="/tmp/core-local-deploy/${title}.log"
    mkdir -p "/tmp/core-local-deploy"
    info "No GUI terminal found — running '$title' in background. Log: $log"
    (cd "$dir" && eval "$cmd") > "$log" 2>&1 &
    BG_PIDS+=($!)
    BG_NAMES+=("$title")
    echo "  PID $! → $log"
  fi
}

SOURCE_ENV="set -a && source $(printf '%q' "$CORELET_ROOT/.env.local.docker") && set +a"

# ── step 3: UI dev server ─────────────────────────────────────────────────────

info "Starting UI dev server…  ($UI_DIR)"
open_term "${CORELET}-ui" "$UI_DIR" "$SOURCE_ENV && npm run dev"
ok "UI dev server launched"

# ── step 4: API dev server ────────────────────────────────────────────────────

info "Starting API dev server… ($API_DIR)"
open_term "${CORELET}-api" "$API_DIR" "$SOURCE_ENV && ./mvnw clean mn:run"
ok "API dev server launched"

# ── step 5: optional extra services ──────────────────────────────────────────

for svc_dir in "${EXTRA_SERVICES[@]}"; do
  svc_name="$(basename "$svc_dir")"
  info "Starting extra service: $svc_name  ($svc_dir)"

  if [[ -f "$svc_dir/package.json" ]]; then
    run_cmd="$SOURCE_ENV && npm run dev"
  elif [[ -f "$svc_dir/mvnw" ]]; then
    run_cmd="$SOURCE_ENV && ./mvnw clean mn:run"
  elif [[ -f "$svc_dir/Makefile" ]]; then
    run_cmd="$SOURCE_ENV && make run"
  elif [[ -f "$svc_dir/start.sh" ]]; then
    run_cmd="$SOURCE_ENV && bash start.sh"
  else
    echo "  ⚠️  Don't know how to start $svc_name — skipping. Add a start.sh to auto-detect."
    continue
  fi

  open_term "$svc_name" "$svc_dir" "$run_cmd"
  ok "$svc_name launched"
done

echo
ok "All services started for $CORELET."

# ── step 6: verify background processes ──────────────────────────────────────

if (( ${#BG_PIDS[@]} > 0 )); then
  sleep 2
  any_failed=false
  for i in "${!BG_PIDS[@]}"; do
    pid="${BG_PIDS[$i]}"
    name="${BG_NAMES[$i]}"
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "❌  ${name} failed to start (PID ${pid} exited). Log: /tmp/core-local-deploy/${name}.log" >&2
      any_failed=true
    fi
  done
  if $any_failed; then
    die "One or more services failed. Fix the issue then run: core-local-deploy $CORELET --redeploy"
  fi
fi

echo "   Tear down : core-local-deploy $CORELET --teardown"
echo "   Redeploy  : core-local-deploy $CORELET --redeploy"