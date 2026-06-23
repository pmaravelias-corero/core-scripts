# core-scripts

Internal dev tooling for a CORElet-based microservices platform. These are personal/team shell scripts; they are not deployed or published.

## What's here

| File | Purpose |
|---|---|
| `core-local-deploy.sh` | Start or tear down one CORElet project locally |
| `core-sync-projects.sh` | Batch-sync all CORElet repos to their remote default branch |

## Key lists to keep in sync

Both scripts contain a hardcoded list that must be updated when a new CORElet is added:

- `CORELETS` in `core-local-deploy.sh` — drives shell tab-completion only; does not affect runtime behaviour
- `PROJECTS` in `core-sync-projects.sh` — determines which repos are synced

These two lists are intentionally independent: not every project in `PROJECTS` needs a full local-deploy setup, and vice versa.

## Assumed directory layout

```
~/Projects/
  <corelet>/
    .env.local.docker
    docker-compose.dev.yml
    images/
      <corelet>-ui/       # npm project
      <corelet>-api/      # Micronaut/Maven project
      <corelet>-*/        # optional extra services (auto-detected)
```

`core-local-deploy` builds all paths from this layout. If the structure differs for a specific corelet, the script will fail early with a clear error.

## Extra services auto-detection

When `core-local-deploy` finds additional directories under `images/` (beyond `-ui` and `-api`), it starts them using the first matching rule:

1. `package.json` present -> `npm run dev`
2. `mvnw` present -> `./mvnw clean mn:run`
3. `Makefile` present -> `make run`
4. `start.sh` present -> `bash start.sh`

If none match, the service is skipped with a warning. The fix is to add a `start.sh` to that service directory.

## Script conventions

- Both scripts use `set -euo pipefail`
- `core-local-deploy` doubles as a shell completion source; the early `return 0` guard at the top is intentional and must be preserved
- `core-sync-projects` reads from `/dev/tty` directly for the dirty-branch prompt so it works correctly inside subshells and pipelines
- Dev server processes run in the background; logs go to `/tmp/core-local-deploy/`. If a supported terminal emulator is detected, each service opens in its own window instead.

## What not to change

- Do not add inter-script dependencies or shared libraries; these scripts are meant to be independently usable
- Do not replace the hardcoded `CORELETS`/`PROJECTS` lists with dynamic discovery; the explicit list is intentional for control over what gets touched
- The terminal emulator detection order in `open_term()` is preference-ordered; do not reorder without reason
