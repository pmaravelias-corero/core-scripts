# core-scripts

Local dev tooling for CORElet-based projects.

## Tools

| Tool | Purpose |
|---|---|
| `core-local-deploy` | Start (or tear down) a single CORElet project locally |
| `core-sync-projects` | Fetch, reset to main, and prune all CORElet projects at once |
| `core-mcp` | Read-only MCP server giving Claude Code ambient knowledge of the workspace |
| `core-dev-hub` | Local browser dashboard with tabbed views (GitHub PRs, Dependabot, and more) |

---

## Installation

### Shell scripts

Both scripts are designed to live in `~/Projects/core-scripts/` and be symlinked into your `$PATH`.

```bash
# Make executable (already set, but just in case)
chmod +x ~/Projects/core-scripts/core-local-deploy/core-local-deploy.sh
chmod +x ~/Projects/core-scripts/core-sync-projects/core-sync-projects.sh

# Symlink into PATH
sudo ln -s ~/Projects/core-scripts/core-local-deploy/core-local-deploy.sh /usr/local/bin/core-local-deploy
sudo ln -s ~/Projects/core-scripts/core-sync-projects/core-sync-projects.sh /usr/local/bin/core-sync-projects
```

### Shell completion for `core-local-deploy`

Add the following to your `~/.bashrc` or `~/.zshrc` so tab-completion works for corelet names and flags:

```bash
source /usr/local/bin/core-local-deploy
```

### MCP server

```bash
cd ~/Projects/core-scripts/core-mcp
bash install.sh
```

`install.sh` runs `pip3 install mcp[cli]`, makes the script executable, and runs `claude mcp add` so Claude Code spawns it automatically.

Verify:

```bash
claude mcp list
# inside a claude session:
/mcp
```

---

## core-local-deploy

Start all services for a CORElet project locally: Docker infrastructure, a UI dev server, and an API dev server.

### Prerequisites

Inside the CORElet project root (`~/Projects/<corelet>/`):
- `.env.local.docker` — environment variables for local Docker
- `docker-compose.dev.yml` — Docker Compose file for infrastructure services

Inside `~/Projects/<corelet>/images/`:
- `<corelet>-ui/` — frontend service (started with `npm run dev`)
- `<corelet>-api/` — backend service (started with `./mvnw clean mn:run`)

### Usage

```bash
# Start all services
core-local-deploy <corelet-name>

# Start and tail all dev-server logs (background mode only; Ctrl-C to stop tailing)
core-local-deploy <corelet-name> --tail-logs

# Tear down and immediately redeploy (e.g. after changing a Docker service or fixing the env file)
core-local-deploy <corelet-name> --redeploy

# Redeploy and tail logs
core-local-deploy <corelet-name> --redeploy --tail-logs

# Tear down all services
core-local-deploy <corelet-name> --teardown

# Tear down all services and remove Docker volumes
core-local-deploy <corelet-name> --teardown-v

# Restart only dev servers (UI and API)
core-local-deploy <corelet-name> --restart-dev

# Restart only dev servers (UI and API) and tail all dev-server logs (background mode only; Ctrl-C to stop tailing)
core-local-deploy <corelet-name> --restart-dev --tail-logs
```

### Example

```bash
core-local-deploy corelet-ztac
core-local-deploy corelet-ztac --tail-logs
core-local-deploy corelet-ztac --redeploy --tail-logs
core-local-deploy corelet-ztac --teardown
core-local-deploy corelet-ztac --teardown-v
core-local-deploy corelet-ztac --restart-dev
core-local-deploy corelet-ztac --restart-dev --tail-logs
```

### What it does

1. Brings up Docker services (`docker compose up -d`)
2. Starts the UI dev server as a background process, logging to `/tmp/core-local-deploy/<corelet>-ui.log`
3. Starts the API dev server as a background process, logging to `/tmp/core-local-deploy/<corelet>-api.log`
4. Detects and starts any extra services found under `images/` (auto-detects `package.json`, `mvnw`, `Makefile`, or `start.sh`)

The script validates that the env file can actually be sourced before starting anything, so a syntax error in `.env.local.docker` fails fast with a clear message rather than silently starting broken processes.

In background mode, the script waits 2 seconds after all services are started and checks that each process is still alive. If any exited immediately, it reports which ones failed and points to their log files.

`--teardown` kills dev server processes, removes log files, and runs `docker compose down`. `--teardown-v` also removes Docker volumes. `--redeploy` runs teardown (Docker volumes are not destroyed) then immediately starts everything again.

If a supported terminal emulator is available (kitty, wezterm, gnome-terminal, x-terminal-emulator, macOS Terminal), each service opens in its own window instead of running in the background.

### Adding a new CORElet

Add the repo name to the `CORELETS` array near the top of `core-local-deploy/core-local-deploy.sh` so it appears in tab-completion:

```bash
CORELETS=(
  corelet-ta
  corelet-ztac
  corelet-auth-mgmt
  corelet-tenant-provisioning
  corelet-your-new-one   # add here
)
```

---

## core-sync-projects

Reset all CORElet projects to the tip of their default remote branch and clean up stale refs and merged branches. Useful after a sprint or before starting new work.

### Usage

```bash
core-sync-projects
```

You can override the projects root directory with an environment variable:

```bash
PROJECTS_DIR=/some/other/path core-sync-projects
```

### What it does

For each project in the list:

1. Checks the directory and git repo exist
2. Detects uncommitted changes and prompts: **Continue**, **Stash & Re-apply**, or **Abort**
3. Fetches from origin (`git fetch --prune`)
4. Checks out the default branch and resets hard to `origin/<branch>`
5. Prunes stale remote-tracking refs
6. Deletes local branches fully merged into HEAD (skips `main`, `master`, `develop`, `dev`)

Prints a summary of OK / Skipped / Failed projects at the end.

### Adding a new project

Add the repo directory name to the `PROJECTS` array near the top of `core-sync-projects/core-sync-projects.sh`:

```bash
PROJECTS=(
  corelet-shell
  corelet-ta
  corelet-ztac
  corelet-auth-mgmt
  corelet-ipintel-plus
  corelet-common
  corelet-chassis
  corelet-your-new-one   # add here
)
```

---

## core-mcp

Read-only MCP server that gives Claude Code ambient knowledge of the CORE workspace — so you never have to re-explain the architecture at the start of a session.

### Tools

| Tool | What Claude learns |
|---|---|
| `get_workspace_overview` | Full workspace map: all CORElets, shell, MF remotes, routing convention |
| `list_corelets` | Every CORElet repo, its image dirs, and inter-corelet dependencies |
| `get_corelet_info` | One CORElet in full: layout, env vars, compose services, MF config, controllers |
| `get_api_routes` | Every `@Controller` endpoint in a CORElet's Micronaut API |
| `get_docker_stack` | Docker Compose services + env vars for a CORElet's dev stack |
| `get_module_federation_graph` | Full MF wiring: what each CORElet exposes vs what the shell registers |
| `resolve_api_route` | Traces any `/api/<name>/...` path hop-by-hop to the matching controller |

### Example prompts

```
"What CORElets do we have and how are they connected?"
"Walk me through how a request to /api/auth-mgmt/users/create flows end-to-end"
"What does corelet-ta expose as MF modules?"
"Which remotes does the shell register that don't have a matching CORElet?"
"What infrastructure does corelet-ztac depend on in its Docker stack?"
"What endpoints does the auth-mgmt API expose?"
"I need to add a new route to corelet-user-settings — what's the existing structure?"
```

---

## core-dev-hub

A local, no-build browser dashboard for day-to-day CORE development. Open `core-dev-hub/index.html` directly in any browser.

A Windows Desktop shortcut is provided for quick access from outside WSL.

### Tabs

| Tab | What it shows |
|---|---|
| GitHub PRs | PRs awaiting your review, your open PRs, and Dependabot dependency bumps across all CORE repos |

### Adding a new tab

1. Create `core-dev-hub/tabs/<tab-name>.js` with your data-fetching and rendering logic.
2. Call `registerTab('<tab-name>', yourLoaderFn)` at the bottom of the file.
3. Add a `<button class="tab">` to the `<nav class="tab-bar">` in `index.html`.
4. Add a `<div id="tab-<tab-name>" class="tab-panel">` with a grid or content wrapper in `index.html`.

The shared utilities available to all tab scripts are: `gh()`, `ageLabel()`, `labelChip()`, `checkDot()`, `loadingCard()`, `errorCard()`, `token()`.

### GitHub token

The token is stored in `localStorage` under the key `gh_token`. Enter it once via the 🔑 button; it persists across browser sessions and is never committed to source.
