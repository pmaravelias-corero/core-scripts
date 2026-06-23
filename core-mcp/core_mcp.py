#!/usr/bin/env python3
"""
core-mcp — read-only knowledge MCP for the CORE workspace.

Gives Claude Code ambient understanding of the CORElet ecosystem:
repo structure, Module Federation wiring, auth-bff routing, Docker stacks,
Micronaut controllers, and inter-corelet dependencies.
No start/stop — purely informational.
"""

from __future__ import annotations

import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ── constants ──────────────────────────────────────────────────────────────────

PROJECTS_ROOT = Path.home() / "Projects"
SHELL_REPO    = PROJECTS_ROOT / "corelet-shell"

PORT_SHELL    = 3000
PORT_UI       = 3001
PORT_AUTH_BFF = 3009
PORT_API      = 9090

# ── server ─────────────────────────────────────────────────────────────────────

mcp = MCPServer(
    name="core-mcp",
    instructions=(
        "You have deep knowledge of the CORE microservices workspace. "
        "Before helping with any feature, bug, or architecture question, "
        "call the relevant tools so you understand the actual structure — "
        "never ask the user to re-explain how CORElets, the shell, or auth-bff work. "
        "CORElets live in ~/Projects/corelet-<name>. "
        "corelet-shell is a monorepo containing two components under its images/ directory: "
        "corelet-shell-ui (the Module Federation host shell, port 3000) and "
        "corelet-shell-api (the auth-bff proxy, port 3009). "
        "auth-bff authenticates sessions and routes /api/<corelet-name>/... "
        "to the matching CORElet's Micronaut API on port 9090."
    ),
)

# ── internal helpers ───────────────────────────────────────────────────────────

def _corelet_dirs() -> list[Path]:
    """All corelet-* repos under ~/Projects (excluding corelet-shell)."""
    if not PROJECTS_ROOT.exists():
        return []
    return sorted(
        p for p in PROJECTS_ROOT.iterdir()
        if p.is_dir()
        and p.name.startswith("corelet-")
        and p.name != "corelet-shell"
        and (p / "docker-compose.dev.yml").exists()
    )


def _bare(repo_dir: Path) -> str:
    """corelet-auth-mgmt  →  auth-mgmt"""
    return repo_dir.name.removeprefix("corelet-")


def _parse_env(env_file: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _parse_compose_services(compose_file: Path) -> list[dict]:
    """
    Parse docker-compose.dev.yml without a YAML library.
    Returns [{name, image, ports, depends_on}].
    """
    if not compose_file.exists():
        return []

    services: list[dict] = []
    current: dict | None = None
    in_services_block = False
    in_ports = False
    in_depends = False

    for raw in compose_file.read_text(errors="replace").splitlines():
        line    = raw.rstrip()
        stripped = line.strip()

        if stripped == "services:":
            in_services_block = True
            continue
        if not in_services_block:
            continue

        # top-level service key (exactly 2-space indent)
        if re.match(r"^  [a-zA-Z0-9_-]+\s*:", line) and not line.startswith("    "):
            if current:
                services.append(current)
            m = re.match(r"^  ([a-zA-Z0-9_-]+)\s*:", line)
            current = {"name": m.group(1), "image": None, "ports": [], "depends_on": []}
            in_ports = in_depends = False
            continue

        if current is None:
            continue

        if stripped.startswith("image:"):
            current["image"] = stripped.split(":", 1)[1].strip()
            in_ports = in_depends = False
        elif stripped == "ports:":
            in_ports, in_depends = True, False
        elif stripped == "depends_on:":
            in_depends, in_ports = True, False
        elif stripped.startswith("- ") and in_ports:
            current["ports"].append(stripped[2:].strip().strip('"'))
        elif stripped.startswith("- ") and in_depends:
            current["depends_on"].append(stripped[2:].strip())
        elif stripped and not stripped.startswith("-") and ":" in stripped:
            in_ports = in_depends = False

    if current:
        services.append(current)
    return services


def _parse_mf_config(search_dir: Path) -> dict | None:
    """
    Parse Module Federation config from common file names.
    Returns {source_file, name, exposes, remotes, shared} or None.
    """
    candidates = [
        "module.federation.config.js",
        "module.federation.config.ts",
        "rspack.config.js",
        "rspack.config.ts",
        "webpack.config.js",
        "webpack.config.ts",
    ]
    for fname in candidates:
        f = search_dir / fname
        if not f.exists():
            continue
        src = f.read_text(errors="replace")
        result: dict = {"source_file": fname}

        m = re.search(r"\bname\s*:\s*[\"']([^\"']+)[\"']", src)
        if m:
            result["name"] = m.group(1)

        exposes: dict[str, str] = {}
        in_exp = False
        for line in src.splitlines():
            s = line.strip()
            if re.search(r"\bexposes\s*:", s):
                in_exp = True
            if in_exp:
                em = re.search(r"[\"'](\./[^\"']+)[\"']\s*:\s*[\"']([^\"']+)[\"']", s)
                if em:
                    exposes[em.group(1)] = em.group(2)
                if s.startswith("}") and exposes:
                    in_exp = False
        if exposes:
            result["exposes"] = exposes

        remotes: dict[str, str] = {}
        in_rem = False
        for line in src.splitlines():
            s = line.strip()
            if re.search(r"\bremotes\s*:", s):
                in_rem = True
            if in_rem:
                rm = re.search(r"[\"']?([a-zA-Z0-9_-]+)[\"']?\s*:\s*[\"']([^\"']*@[^\"']+)[\"']", s)
                if rm:
                    remotes[rm.group(1)] = rm.group(2)
                if s.startswith("}") and remotes:
                    in_rem = False
        if remotes:
            result["remotes"] = remotes

        shared: list[str] = re.findall(
            r"[\"']([a-zA-Z@][^\"']*)[\"'](?=\s*:\s*\{[^}]*requiredVersion)", src
        )
        if shared:
            result["shared"] = shared

        return result
    return None


def _parse_controllers(api_dir: Path) -> list[dict]:
    """
    Walk src/main/java for files containing @Controller.
    Returns [{file, controller_path, endpoints:[{method, path, signature}]}].
    """
    src_root = api_dir / "src" / "main" / "java"
    if not src_root.exists():
        return []

    results: list[dict] = []
    for java_file in sorted(src_root.rglob("*.java")):
        src = java_file.read_text(errors="replace")
        if "@Controller" not in src:
            continue

        cm = re.search(r"@Controller\s*\(\s*[\"']([^\"']*)[\"']", src)
        ctrl_path = cm.group(1) if cm else "/"

        endpoints: list[dict] = []
        for mm in re.finditer(
            r"@(Get|Post|Put|Delete|Patch)\s*(?:\(\s*[\"']([^\"']*)[\"'](?:\s*,.*?)?\s*\))?\s*\n"
            r"(?:\s*(?:@\w+[^\n]*\n))*"
            r"\s*(public\s+[^\n{]+)",
            src,
        ):
            http_method = mm.group(1).upper()
            method_path = (mm.group(2) or "").strip()
            signature   = " ".join(mm.group(3).split())
            full_path   = ctrl_path.rstrip("/") + ("/" + method_path.lstrip("/") if method_path else "")
            endpoints.append({
                "method":    http_method,
                "path":      full_path or "/",
                "signature": signature,
            })

        results.append({
            "file":            str(java_file.relative_to(api_dir)),
            "controller_path": ctrl_path,
            "endpoints":       endpoints,
        })
    return results


def _find_corelet_refs(path: Path, all_names: list[str]) -> list[str]:
    """Scan env + compose files for references to other corelet names."""
    haystack = ""
    for fname in [".env.local.docker", "docker-compose.dev.yml"]:
        f = path / fname
        if f.exists():
            haystack += f.read_text(errors="replace")

    found: set[str] = set()
    for name in all_names:
        if name == _bare(path):
            continue
        if re.search(rf"\bcorelet[-_]{re.escape(name)}\b", haystack, re.IGNORECASE):
            found.add(name)
    return sorted(found)


# ── tools ──────────────────────────────────────────────────────────────────────

@mcp.tool(description=(
    "e.g. 'what CORElets do we have?', 'list all corelets', 'what projects are in CORE?'. "
    "Return a summary of every CORElet in ~/Projects: repo name, bare name, "
    "path, which image directories exist, and inter-corelet dependencies. "
    "Call this first in any session to orient yourself. "
    "Never ask the user which CORElets exist — read it here."
))
def list_corelets() -> dict:
    dirs  = _corelet_dirs()
    names = [_bare(d) for d in dirs]

    corelets = []
    for path in dirs:
        name   = _bare(path)
        images = path / "images"
        image_dirs = sorted(d.name for d in images.iterdir() if d.is_dir()) if images.exists() else []
        corelets.append({
            "name":       name,
            "repo":       path.name,
            "path":       str(path),
            "image_dirs": image_dirs,
            "depends_on": _find_corelet_refs(path, names),
        })

    return {
        "projects_root": str(PROJECTS_ROOT),
        "corelet_count": len(corelets),
        "corelets":      corelets,
        "shell": {
            "repo":     "corelet-shell",
            "path":     str(SHELL_REPO),
            "exists":   SHELL_REPO.exists(),
            "port_ui":  PORT_SHELL,
            "port_bff": PORT_AUTH_BFF,
        },
        "well_known_ports": {
            "shell_ui":    PORT_SHELL,
            "corelet_ui":  PORT_UI,
            "auth_bff":    PORT_AUTH_BFF,
            "corelet_api": PORT_API,
        },
    }


@mcp.tool(description=(
    "e.g. 'tell me about the auth-mgmt corelet', 'how is user-settings structured?', 'show me the corelet info for ztac'. "
    "Return the full structural picture for one CORElet: "
    "directory layout, env vars, Docker Compose services, Module Federation config, "
    "and Micronaut controller/endpoint inventory. "
    "Use this whenever you need to understand a specific CORElet before "
    "writing code, tracing a bug, or explaining how it is wired. "
    "corelet_name: bare name without the 'corelet-' prefix, e.g. 'auth-mgmt'."
))
def get_corelet_info(corelet_name: str) -> dict:
    path    = PROJECTS_ROOT / f"corelet-{corelet_name}"
    images  = path / "images"
    ui_dir  = images / f"corelet-{corelet_name}-ui"
    api_dir = images / f"corelet-{corelet_name}-api"

    if not path.exists():
        return {"error": f"CORElet not found: ~/Projects/corelet-{corelet_name}"}

    extra_services: list[dict] = []
    if images.exists():
        for d in sorted(images.iterdir()):
            if not d.is_dir():
                continue
            if d.name in (f"corelet-{corelet_name}-ui", f"corelet-{corelet_name}-api"):
                continue
            if d.name.startswith(f"corelet-{corelet_name}-"):
                kind = (
                    "node"      if (d / "package.json").exists() else
                    "micronaut" if (d / "mvnw").exists() else
                    "other"
                )
                extra_services.append({"name": d.name, "path": str(d), "kind": kind})

    all_names = [_bare(d) for d in _corelet_dirs()]

    return {
        "name": corelet_name,
        "repo": f"corelet-{corelet_name}",
        "path": str(path),
        "ui": {
            "path":   str(ui_dir),
            "exists": ui_dir.exists(),
            "port":   PORT_UI,
            "url":    f"http://localhost:{PORT_UI}",
        },
        "api": {
            "path":   str(api_dir),
            "exists": api_dir.exists(),
            "port":   PORT_API,
            "url":    f"http://localhost:{PORT_API}",
        },
        "extra_services":    extra_services,
        "env_vars":          _parse_env(path / ".env.local.docker"),
        "compose_services":  _parse_compose_services(path / "docker-compose.dev.yml"),
        "module_federation": _parse_mf_config(ui_dir) if ui_dir.exists() else None,
        "controllers":       _parse_controllers(api_dir) if api_dir.exists() else [],
        "depends_on":        _find_corelet_refs(path, all_names),
        "auth_bff_prefix":   f"/api/{corelet_name}",
        "routing_note": (
            f"auth-bff (:{PORT_AUTH_BFF}) matches /api/{corelet_name}/* "
            f"and forwards the remainder to http://localhost:{PORT_API}"
        ),
    }


@mcp.tool(description=(
    "e.g. 'how are the MF remotes wired?', 'what does each corelet expose?', 'which remotes is the shell missing?'. "
    "Return the full Module Federation picture across the entire workspace: "
    "what each CORElet exposes, what the shell registers as remotes, and "
    "which CORElets are missing from the shell's remote list or vice-versa. "
    "Use this when working on cross-corelet UI integration, adding a new "
    "exposed component, or debugging MF wiring issues."
))
def get_module_federation_graph() -> dict:
    shell_ui  = SHELL_REPO / "images" / "corelet-shell-ui"
    shell_mf  = _parse_mf_config(shell_ui) if shell_ui.exists() else None
    shell_remotes: dict[str, str] = (shell_mf or {}).get("remotes", {})

    corelet_exposures: list[dict] = []
    for path in _corelet_dirs():
        name   = _bare(path)
        ui_dir = path / "images" / f"corelet-{name}-ui"
        mf     = _parse_mf_config(ui_dir) if ui_dir.exists() else None
        in_shell = any(
            name in url or name.replace("-", "") in key
            for key, url in shell_remotes.items()
        )
        corelet_exposures.append({
            "name":                name,
            "mf_name":             (mf or {}).get("name"),
            "exposes":             (mf or {}).get("exposes", {}),
            "shared":              (mf or {}).get("shared", []),
            "mf_config_file":      (mf or {}).get("source_file"),
            "registered_in_shell": in_shell,
        })

    registered_names    = set(shell_remotes.keys())
    corelet_mf_names    = {c["mf_name"] for c in corelet_exposures if c["mf_name"]}
    in_shell_not_found  = sorted(registered_names - corelet_mf_names)
    has_mf_not_in_shell = [c["name"] for c in corelet_exposures if c["exposes"] and not c["registered_in_shell"]]

    return {
        "shell": {
            "path":           str(shell_ui),
            "mf_config_file": (shell_mf or {}).get("source_file"),
            "name":           (shell_mf or {}).get("name"),
            "remotes":        shell_remotes,
            "shared":         (shell_mf or {}).get("shared", []),
        },
        "corelets":                   corelet_exposures,
        "in_shell_not_found":         in_shell_not_found,
        "has_exposures_not_in_shell": has_mf_not_in_shell,
    }


@mcp.tool(description=(
    "e.g. 'what endpoints does auth-mgmt expose?', 'show me the API routes for ztac', 'what controllers does user-settings have?'. "
    "Parse the Micronaut @Controller source files for a CORElet and return "
    "every HTTP endpoint: method, full path, and Java method signature. "
    "Use this to understand what the API actually exposes before writing "
    "frontend fetch calls, tests, or debugging 404s. "
    "corelet_name: bare name, e.g. 'auth-mgmt'."
))
def get_api_routes(corelet_name: str) -> dict:
    api_dir = PROJECTS_ROOT / f"corelet-{corelet_name}" / "images" / f"corelet-{corelet_name}-api"
    if not api_dir.exists():
        return {"error": f"API dir not found: {api_dir}"}

    controllers = _parse_controllers(api_dir)
    if not controllers:
        return {
            "corelet":     corelet_name,
            "controllers": [],
            "note":        "No @Controller classes found under src/main/java",
        }

    all_endpoints = [
        {
            "method":          ep["method"],
            "full_path":       f"/api/{corelet_name}{ep['path']}",
            "java_path":       ep["path"],
            "signature":       ep["signature"],
            "controller_file": c["file"],
        }
        for c in controllers
        for ep in c["endpoints"]
    ]

    return {
        "corelet":        corelet_name,
        "api_base_url":   f"http://localhost:{PORT_API}",
        "bff_prefix":     f"/api/{corelet_name}",
        "controllers":    controllers,
        "all_endpoints":  all_endpoints,
        "endpoint_count": len(all_endpoints),
    }


@mcp.tool(description=(
    "e.g. 'what services does auth-mgmt run?', 'what infrastructure does ztac depend on?', 'show me the docker stack for tenant-provisioning'. "
    "Return the Docker Compose service list for a CORElet's dev stack: "
    "service names, images, port mappings, inter-service dependencies, "
    "and the env vars that configure them. "
    "Use this to understand what infrastructure a CORElet depends on "
    "(etcd, minio, postgres, loki, etc.) and how services are wired together. "
    "corelet_name: bare name, e.g. 'auth-mgmt'."
))
def get_docker_stack(corelet_name: str) -> dict:
    path    = PROJECTS_ROOT / f"corelet-{corelet_name}"
    compose = path / "docker-compose.dev.yml"
    env_file = path / ".env.local.docker"

    if not path.exists():
        return {"error": f"CORElet not found: ~/Projects/corelet-{corelet_name}"}

    env_vars = _parse_env(env_file)
    services = _parse_compose_services(compose)

    # Annotate each service with likely-relevant env vars
    for svc in services:
        svc_key = svc["name"].upper().replace("-", "_")
        svc["relevant_env_vars"] = {
            k: v for k, v in env_vars.items() if svc_key in k
        }

    return {
        "corelet":       corelet_name,
        "compose_file":  str(compose),
        "env_file":      str(env_file),
        "service_count": len(services),
        "services":      services,
        "all_env_vars":  env_vars,
    }


@mcp.tool(description=(
    "e.g. 'where does /api/auth-mgmt/users/create go?', 'trace this request: /api/ztac/roles', 'why is this API path returning 404?'. "
    "Given any request path from the browser or shell, "
    "explain the full routing chain: which CORElet handles it, the auth-bff forwarding rule, "
    "the downstream Micronaut URL, and which controller endpoint matches. "
    "Use this when tracing a request end-to-end, debugging 404s/401s, or explaining "
    "how a particular API call flows through the system."
))
def resolve_api_route(request_path: str) -> dict:
    path  = request_path.lstrip("/")
    parts = path.split("/")

    if len(parts) < 2 or parts[0] != "api":
        return {
            "error":   "Path must start with /api/<corelet-name>/…",
            "example": "/api/auth-mgmt/users/create",
        }

    corelet_name = parts[1]
    downstream   = "/" + "/".join(parts[2:]) if len(parts) > 2 else "/"
    corelet_path = PROJECTS_ROOT / f"corelet-{corelet_name}"

    if not corelet_path.exists():
        return {
            "error":          f"No CORElet named '{corelet_name}' in ~/Projects",
            "request_path":   "/" + path,
            "known_corelets": [_bare(d) for d in _corelet_dirs()],
        }

    controllers = _parse_controllers(
        corelet_path / "images" / f"corelet-{corelet_name}-api"
    )
    matched = [
        ep for c in controllers for ep in c["endpoints"]
        if ep["path"].rstrip("/") == downstream.rstrip("/")
        or re.fullmatch(
            re.sub(r"\{[^}]+\}", "[^/]+", re.escape(ep["path"])),
            downstream.rstrip("/"),
        )
    ]

    return {
        "request_path": "/" + path,
        "routing_chain": [
            {
                "hop":      1,
                "label":    "Browser / corelet-shell",
                "sends_to": f"http://localhost:{PORT_AUTH_BFF}/api/{corelet_name}{downstream}",
            },
            {
                "hop":      2,
                "label":    "auth-bff",
                "port":     PORT_AUTH_BFF,
                "rule":     f"Strips /api/{corelet_name}, authenticates session, forwards to CORElet API",
                "sends_to": f"http://localhost:{PORT_API}{downstream}",
            },
            {
                "hop":      3,
                "label":    f"corelet-{corelet_name} Micronaut API",
                "port":     PORT_API,
                "downstream_path":     downstream,
                "matched_endpoints":   matched,
            },
        ],
        "corelet":           corelet_name,
        "downstream_path":   downstream,
        "matched_endpoints": matched,
        "match_note": (
            "Exact or path-variable match found." if matched
            else "No controller endpoint matched — possible 404 or route not yet implemented."
        ),
    }


@mcp.tool(description=(
    "e.g. 'give me an overview of the CORE workspace', 'show me the full architecture', 'orient yourself in CORE'. "
    "Return a high-level map of the entire CORE workspace in one call: "
    "every CORElet, the shell, all MF remote registrations, and the "
    "auth-bff routing convention. "
    "Use this at the start of cross-cutting tasks — adding a new CORElet, "
    "refactoring shared infrastructure, or understanding how the whole system fits together."
))
def get_workspace_overview() -> dict:
    dirs  = _corelet_dirs()
    names = [_bare(d) for d in dirs]

    shell_ui = SHELL_REPO / "images" / "corelet-shell-ui"
    shell_mf = _parse_mf_config(shell_ui) if shell_ui.exists() else None

    corelets = []
    for path in dirs:
        name    = _bare(path)
        ui_dir  = path / "images" / f"corelet-{name}-ui"
        api_dir = path / "images" / f"corelet-{name}-api"
        mf      = _parse_mf_config(ui_dir) if ui_dir.exists() else None
        corelets.append({
            "name":             name,
            "repo":             path.name,
            "auth_bff_prefix":  f"/api/{name}",
            "ui_port":          PORT_UI,
            "api_port":         PORT_API,
            "mf_name":          (mf or {}).get("name"),
            "exposes":          list((mf or {}).get("exposes", {}).keys()),
            "controller_files": len(_parse_controllers(api_dir)) if api_dir.exists() else 0,
            "compose_services": len(_parse_compose_services(path / "docker-compose.dev.yml")),
            "depends_on":       _find_corelet_refs(path, names),
        })

    return {
        "workspace": str(PROJECTS_ROOT),
        "architecture": {
            "pattern":      "Module Federation microfrontends + Micronaut microservices",
            "corelet_shell": (
                f"corelet-shell is a monorepo with two components in images/: "
                f"corelet-shell-ui (MF host shell, port {PORT_SHELL}) which registers all CORElet remotes, "
                f"and corelet-shell-api (auth-bff, port {PORT_AUTH_BFF}) which authenticates sessions "
                f"and proxies /api/<corelet-name>/... to the matching CORElet API"
            ),
            "corelet_ui":   f"Each CORElet UI runs on port {PORT_UI} as a Module Federation remote",
            "corelet_api":  f"Each CORElet Micronaut API runs on port {PORT_API}",
            "infra":        "Docker Compose per CORElet (dev stack); Kubernetes via core-platform (prod)",
        },
        "shell": {
            "path":    str(SHELL_REPO),
            "exists":  SHELL_REPO.exists(),
            "mf_name": (shell_mf or {}).get("name"),
            "remotes": (shell_mf or {}).get("remotes", {}),
        },
        "corelets": corelets,
    }


# ── cross-referencing tools ────────────────────────────────────────────────────

@mcp.tool(description=(
    "e.g. 'where is AuthService used?', 'which CORElets reference etcd?', 'find all usages of USER_SERVICE_URL'. "
    "Search across all CORElet repos for a symbol, env var, component name, or any string. "
    "Returns matching file paths, line numbers, and context lines. "
    "Use this when you need to understand the blast radius of a change, find all call sites, "
    "or locate where something is defined or referenced across the workspace."
))
def find_usages(symbol: str, file_extensions: list[str] | None = None) -> dict:
    """
    symbol: the string to search for (partial matches included).
    file_extensions: optional filter, e.g. ['.java', '.ts', '.tsx']. Defaults to all text files.
    """
    import subprocess

    extensions = file_extensions or [".java", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml", ".env", ".md"]

    matches: list[dict] = []
    searched_dirs: list[str] = []

    search_dirs = _corelet_dirs() + ([SHELL_REPO] if SHELL_REPO.exists() else [])

    for repo_dir in search_dirs:
        searched_dirs.append(repo_dir.name)
        # Build include args for grep
        include_args = [f"--include=*{ext}" for ext in extensions]
        cmd = [
            "grep", "-rn", "--with-filename",
            *include_args,
            symbol,
            str(repo_dir),
        ]
        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=15)
            for line in out.splitlines():
                # format: /path/to/file.java:42:    content
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_path, lineno, content = parts
                rel = Path(file_path).relative_to(PROJECTS_ROOT)
                matches.append({
                    "repo":    repo_dir.name,
                    "file":    str(rel),
                    "line":    int(lineno),
                    "content": content.strip(),
                })
        except subprocess.CalledProcessError:
            pass  # grep returns exit 1 when no matches — not an error
        except subprocess.TimeoutExpired:
            matches.append({"error": f"Timed out searching {repo_dir.name}"})

    # Group by repo for readability
    by_repo: dict[str, list] = {}
    for m in matches:
        by_repo.setdefault(m.get("repo", "?"), []).append(m)

    return {
        "symbol":        symbol,
        "match_count":   len(matches),
        "searched_dirs": searched_dirs,
        "by_repo":       by_repo,
    }


@mcp.tool(description=(
    "e.g. 'how are the CORElets connected?', 'what depends on auth-mgmt?', 'show the dependency graph'. "
    "Return a map of inter-corelet dependencies derived from env files and docker-compose configs: "
    "which CORElets reference each other, and which shared infrastructure services each one uses. "
    "Use this to understand the blast radius of a change, plan a refactor, "
    "or reason about startup order."
))
def get_dependency_graph() -> dict:
    dirs  = _corelet_dirs()
    names = [_bare(d) for d in dirs]

    # Collect all docker-compose services across all corelets to find shared infra
    infra_users: dict[str, list[str]] = {}  # service_name → [corelet names that use it]
    corelet_deps: list[dict] = []

    for path in dirs:
        name     = _bare(path)
        deps     = _find_corelet_refs(path, names)
        services = _parse_compose_services(path / "docker-compose.dev.yml")
        svc_names = [s["name"] for s in services]

        for svc in svc_names:
            infra_users.setdefault(svc, []).append(name)

        corelet_deps.append({
            "corelet":          name,
            "depends_on":       deps,
            "compose_services": svc_names,
        })

    # Shared infra = services used by more than one corelet
    shared_infra = {
        svc: users for svc, users in infra_users.items() if len(users) > 1
    }

    # Reverse map: for each corelet, who depends on it
    depended_on_by: dict[str, list[str]] = {n: [] for n in names}
    for entry in corelet_deps:
        for dep in entry["depends_on"]:
            if dep in depended_on_by:
                depended_on_by[dep].append(entry["corelet"])

    return {
        "corelets":      corelet_deps,
        "depended_on_by": depended_on_by,
        "shared_infra":  shared_infra,
        "summary": (
            f"{len(dirs)} CORElets. "
            f"Shared infrastructure services: {', '.join(sorted(shared_infra.keys())) or 'none detected'}."
        ),
    }


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
