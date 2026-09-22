#!/usr/bin/env python3
"""Add or update one plugin entry in registry.json.

    python3 scripts/add-plugin.py neilforest7/mimo-cliproxyapi
    python3 scripts/add-plugin.py https://github.com/owner/repo --tags provider,codex
    python3 scripts/add-plugin.py owner/repo --name "Nice Plugin" --description "..." --dry-run
    python3 scripts/add-plugin.py --self-check

The entry is derived from the plugin repository's latest release: the id comes from the
release asset names (<id>_<version>_<goos>_<goarch>.zip), the version from the release tag,
and the license from the GitHub API. An entry with the same id or repository is replaced.
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_registry import ID_RE, VERSION_RE, validate_registry  # noqa: E402

REGISTRY = Path(__file__).resolve().parents[1] / "registry.json"
ASSET_RE = re.compile(
    r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})_(?P<version>[0-9][0-9A-Za-z.+-]*)_[a-z0-9]+_[a-z0-9]+\.zip$"
)
GH_API_ROOT = "https://api.github.com"


def repository_from(value: str) -> str:
    """Normalize owner/repo or a GitHub URL into https://github.com/{owner}/{repo}."""
    value = value.strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = value[len("git@github.com:") :]
    elif value.startswith(("https://", "http://")):
        parsed = urllib.parse.urlparse(value)
        if parsed.netloc.lower() not in ("github.com", "www.github.com"):
            raise SystemExit(f"not a github repository: {value}")
        value = parsed.path
    value = value.strip("/")
    if value.endswith(".git"):
        value = value[: -len(".git")]
    segments = [segment for segment in value.split("/") if segment]
    if len(segments) != 2:
        raise SystemExit(f"not a github repository: {value}")
    return f"https://github.com/{segments[0]}/{segments[1]}"


def github_api(path: str) -> dict:
    """GET one GitHub API resource. Prefers the gh CLI so authenticated rate limits apply."""
    if shutil.which("gh"):
        result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as err:
                raise SystemExit(f"gh api {path} returned invalid JSON: {err}") from err
        if "HTTP 404" in result.stderr:
            raise SystemExit(f"github.com{path} not found")
        raise SystemExit(f"gh api {path} failed: {result.stderr.strip()}")
    url = f"{GH_API_ROOT}{path}"
    if not url.startswith("https://api.github.com/"):
        raise SystemExit(f"refusing to call a non-github API URL: {url}")
    connection = http.client.HTTPSConnection("api.github.com", timeout=30)
    try:
        connection.request(
            "GET",
            path,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "cliproxyapi-plugins-registry"},
        )
        response = connection.getresponse()
        body = response.read()
    except OSError as err:
        raise SystemExit(f"github API unreachable: {err}") from err
    finally:
        connection.close()
    if response.status != 200:
        raise SystemExit(f"github.com{path} returned HTTP {response.status}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as err:
        raise SystemExit(f"github.com{path} returned invalid JSON: {err}") from err


def release_plugin_id(assets: list[dict]) -> str:
    """Read the plugin id from the release archive names, which must agree."""
    ids = set()
    for asset in assets:
        match = ASSET_RE.match(str(asset.get("name", "")))
        if match:
            ids.add(match.group("id"))
    if not ids:
        raise SystemExit("release has no <id>_<version>_<goos>_<goarch>.zip assets")
    if len(ids) > 1:
        raise SystemExit(f"release mixes plugin ids: {', '.join(sorted(ids))}")
    return ids.pop()


def release_version(tag: str) -> str:
    """Strip the required leading v and check the dotted numeric form."""
    tag = tag.strip()
    if not tag.startswith("v"):
        raise SystemExit(f"release tag {tag!r} must look like v0.1.0")
    version = tag[1:]
    if not VERSION_RE.match(version):
        raise SystemExit(f"release tag {tag!r} does not carry a usable version")
    return version


def build_entry(repository: str, release: dict, repo_info: dict, args: argparse.Namespace) -> dict:
    owner, repo = repository.rsplit("/", 2)[-2:]
    plugin_id = args.id or release_plugin_id(release.get("assets") or [])
    if not ID_RE.match(plugin_id):
        raise SystemExit(f"invalid plugin id {plugin_id!r}")
    description = (args.description or repo_info.get("description") or "").strip()
    if not description:
        raise SystemExit("the plugin repository has no description; pass --description")
    entry = {
        "id": plugin_id,
        "name": (args.name or plugin_id).strip(),
        "description": description,
        "author": (args.author or owner).strip(),
        "repository": repository,
        "homepage": repository,
    }
    license_id = ((repo_info.get("license") or {}) or {}).get("spdx_id") or ""
    if license_id and license_id != "NOASSERTION":
        entry["license"] = license_id
    if args.tags:
        entry["tags"] = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    if not release.get("assets"):
        raise SystemExit(f"{repo} has no release assets yet")
    return entry


def upsert(registry: dict, entry: dict) -> tuple[dict, str]:
    plugins = registry.setdefault("plugins", [])
    for index, existing in enumerate(plugins):
        if existing.get("id") == entry["id"] or existing.get("repository") == entry["repository"]:
            plugins[index] = entry
            return registry, f"updated {entry['id']}"
    plugins.append(entry)
    return registry, f"added {entry['id']}"


def self_check() -> int:
    cases: list[tuple[str, object, object]] = []

    for raw, expected in (
        ("neilforest7/mimo-cliproxyapi", "https://github.com/neilforest7/mimo-cliproxyapi"),
        ("https://github.com/owner/repo/", "https://github.com/owner/repo"),
        ("git@github.com:owner/repo.git", "https://github.com/owner/repo"),
    ):
        cases.append((f"repository_from({raw})", repository_from(raw), expected))

    release = {
        "tag_name": "v0.1.0",
        "assets": [
            {"name": "demo_0.1.0_darwin_arm64.zip"},
            {"name": "demo_0.1.0_linux_amd64.zip"},
            {"name": "checksums.txt"},
        ],
    }
    cases.append(("release_plugin_id", release_plugin_id(release["assets"]), "demo"))
    cases.append(("release_version", release_version(release["tag_name"]), "0.1.0"))

    entry = build_entry(
        "https://github.com/owner/repo",
        release,
        {"description": "Demo plugin.", "license": {"spdx_id": "MIT"}},
        argparse.Namespace(id=None, name=None, description=None, author=None, tags="provider, demo"),
    )
    cases.append(("entry id", entry["id"], "demo"))
    cases.append(("entry author", entry["author"], "owner"))
    cases.append(("entry license", entry["license"], "MIT"))
    cases.append(("entry tags", entry["tags"], ["provider", "demo"]))
    cases.append(("entry passes the registry validator", validate_registry({"schema_version": 1, "plugins": [entry]}), []))

    replaced, action = upsert({"schema_version": 1, "plugins": [entry]}, entry)
    cases.append(("upsert replaces", (action, len(replaced["plugins"])), ("updated demo", 1)))
    appended, action = upsert({"schema_version": 1, "plugins": []}, entry)
    cases.append(("upsert appends", (action, len(appended["plugins"])), ("added demo", 1)))

    failures = 0
    for label, actual, expected in cases:
        if actual != expected:
            failures += 1
            print(f"self-check {label}: expected {expected!r}, got {actual!r}", file=sys.stderr)
    if failures:
        print(f"self-check: {failures}/{len(cases)} case(s) failed", file=sys.stderr)
        return 1
    print(f"self-check: ok ({len(cases)} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Add or update a plugin entry in registry.json")
    parser.add_argument("repository", nargs="?", help="owner/repo or https://github.com/owner/repo")
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--author")
    parser.add_argument("--tags", help="comma separated")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        return self_check()
    if not args.repository:
        parser.error("repository is required (or use --self-check)")

    repository = repository_from(args.repository)
    owner, repo = repository.rsplit("/", 2)[-2:]
    release = github_api(f"/repos/{owner}/{repo}/releases/latest")
    repo_info = github_api(f"/repos/{owner}/{repo}")
    entry = build_entry(repository, release, repo_info, args)

    try:
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        print(f"{args.registry}: {err}", file=sys.stderr)
        return 1
    registry, action = upsert(registry, entry)
    errors = validate_registry(registry)
    if errors:
        print(f"{args.registry}: {len(errors)} problem(s)", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(json.dumps(entry, indent=2))
        print(f"dry run: would have {action}")
        return 0
    args.registry.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    print(f"{action} in {args.registry}: {entry['id']} <- {repository} ({release['tag_name']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
