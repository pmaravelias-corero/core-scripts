# core-scripts

Local dev tooling for CORElet-based projects.

## Scripts

| Script | Purpose |
|---|---|
| `core-local-deploy` | Start (or tear down) a single CORElet project locally |
| `core-sync-projects` | Fetch, reset to main, and prune all CORElet projects at once |

---

## Installation

Both scripts are designed to live in `~/Projects/core-scripts/` and be symlinked into your `$PATH`.

```bash
# Make executable (already set, but just in case)
chmod +x ~/Projects/core-scripts/core-local-deploy.sh
chmod +x ~/Projects/core-scripts/core-sync-projects.sh

# Symlink into PATH
sudo ln -s ~/Projects/core-scripts/core-local-deploy.sh /usr/local/bin/core-local-deploy
sudo ln -s ~/Projects/core-scripts/core-sync-projects.sh /usr/local/bin/core-sync-projects
```

### Shell completion for `core-local-deploy`

Add the following to your `~/.bashrc` or `~/.zshrc` so tab-completion works for corelet names and `--teardown`:

```bash
source /usr/local/bin/core-local-deploy
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

# Tear down all services
core-local-deploy <corelet-name> --teardown

# Tear down and immediately redeploy (e.g. after changing a Docker service or fixing the env file)
core-local-deploy <corelet-name> --redeploy
```

### Example

```bash
core-local-deploy corelet-ztac
core-local-deploy corelet-ztac --teardown
core-local-deploy corelet-ztac --redeploy
```

### What it does

1. Brings up Docker services (`docker compose up -d`)
2. Starts the UI dev server as a background process, logging to `/tmp/core-local-deploy/<corelet>-ui.log`
3. Starts the API dev server as a background process, logging to `/tmp/core-local-deploy/<corelet>-api.log`
4. Detects and starts any extra services found under `images/` (auto-detects `package.json`, `mvnw`, `Makefile`, or `start.sh`)

The script validates that the env file can actually be sourced before starting anything, so a syntax error in `.env.local.docker` fails fast with a clear message rather than silently starting broken processes.

In background mode, the script waits 2 seconds after all services are started and checks that each process is still alive. If any exited immediately, it reports which ones failed and points to their log files.

Teardown kills dev server processes, removes log files, and runs `docker compose down`. `--redeploy` runs teardown then immediately starts everything again.

If a supported terminal emulator is available (kitty, wezterm, gnome-terminal, x-terminal-emulator, macOS Terminal), each service opens in its own window instead of running in the background.

### Adding a new CORElet

Add the repo name to the `CORELETS` array near the top of `core-local-deploy.sh` so it appears in tab-completion:

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

Add the repo directory name to the `PROJECTS` array near the top of `core-sync-projects.sh`:

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
