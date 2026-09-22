#!/usr/bin/env python3
"""Validate registry.json against the CLIProxyAPI plugin store rules.

Mirrors internal/pluginstore/registry.go (SchemaVersion 1 and 2) from
router-for-me/CLIProxyAPI. Run: python3 scripts/validate_registry.py [registry.json]
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOS_ALIASES = {"mac": "darwin", "macos": "darwin", "osx": "darwin"}
GOARCH_ALIASES = {"x64": "amd64", "x86_64": "amd64", "aarch64": "arm64"}
SENSITIVE_QUERY_KEYS = {"token", "access_token", "access_key", "secret", "secret_key", "api_key"}
GITHUB_RELEASE = "github-release"
DIRECT = "direct"


def repo_parts(repository: str) -> bool:
    parsed = urllib.parse.urlparse(repository)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        return False
    segments = [s for s in parsed.path.strip("/").split("/") if s]
    return len(segments) == 2 and not segments[1].endswith(".git")


def install_type(plugin: dict) -> str:
    return str(plugin.get("install", {}).get("type", "")).strip().lower() or GITHUB_RELEASE


def validate_artifact(artifact: dict, where: str, errors: list[str]) -> None:
    goos = GOOS_ALIASES.get(str(artifact.get("goos", "")).strip().lower(), str(artifact.get("goos", "")).strip().lower())
    goarch = GOARCH_ALIASES.get(str(artifact.get("goarch", "")).strip().lower(), str(artifact.get("goarch", "")).strip().lower())
    url = str(artifact.get("url", "")).strip()
    sha256 = str(artifact.get("sha256", "")).strip().lower()
    for field, value in (("goos", goos), ("goarch", goarch), ("url", url), ("sha256", sha256)):
        if not value:
            errors.append(f"{where}: missing {field}")
    if url:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append(f"{where}: artifact url must use http or https")
        elif SENSITIVE_QUERY_KEYS & {k.lower() for k in urllib.parse.parse_qs(parsed.query)}:
            errors.append(f"{where}: artifact url contains sensitive query parameter")
    if sha256 and not SHA256_RE.match(sha256):
        errors.append(f"{where}: invalid sha256")


def validate_install_plan(plan: dict, where: str, errors: list[str]) -> None:
    kind = str(plan.get("type", "")).strip().lower()
    if not kind:
        errors.append(f"{where}: missing install type")
        return
    if kind not in (DIRECT, GITHUB_RELEASE):
        errors.append(f"{where}: unsupported install type {kind!r}")
        return
    if kind != DIRECT:
        return
    artifacts = plan.get("artifacts") or []
    if not artifacts:
        errors.append(f"{where}: direct install requires at least one artifact")
    for index, artifact in enumerate(artifacts):
        validate_artifact(artifact, f"{where}: artifacts[{index}]", errors)


def validate_plugin(plugin: dict, schema_version: int, where: str, errors: list[str]) -> None:
    kind = install_type(plugin)
    required = ("id", "name", "description", "author") + (("repository",) if kind == GITHUB_RELEASE else ())
    for field in required:
        if not str(plugin.get(field, "")).strip():
            errors.append(f"{where}: missing required field {field}")

    plugin_id = str(plugin.get("id", "")).strip()
    if plugin_id and not ID_RE.match(plugin_id):
        errors.append(f"{where}: invalid plugin id {plugin_id!r}")

    version = str(plugin.get("version", "")).strip()
    if version and (version.startswith("v") or not VERSION_RE.match(version)):
        errors.append(f"{where}: invalid plugin version {version!r}")

    repository = str(plugin.get("repository", "")).strip()
    if kind == GITHUB_RELEASE and repository and not repo_parts(repository):
        errors.append(f"{where}: repository must be https://github.com/{{owner}}/{{repo}}")
    if kind == DIRECT and not version:
        errors.append(f"{where}: missing required field version")
    if kind == DIRECT and schema_version == 1:
        errors.append(f"{where}: direct install requires schema_version 2")

    if kind == DIRECT:
        validate_install_plan(plugin.get("install") or {}, f"{where}: install", errors)

    seen_versions: set[str] = set()
    for index, entry in enumerate(plugin.get("versions") or []):
        entry_where = f"{where}: versions[{index}]"
        entry_version = str(entry.get("version", "")).strip()
        if not VERSION_RE.match(entry_version) or entry_version.startswith("v"):
            errors.append(f"{entry_where}: invalid plugin version {entry_version!r}")
        elif entry_version in seen_versions:
            errors.append(f"{entry_where}: duplicate plugin version {entry_version!r}")
        seen_versions.add(entry_version)
        entry_install = entry.get("install") or {}
        entry_kind = str(entry_install.get("type", "")).strip().lower() or kind
        if entry_kind != kind:
            errors.append(f"{entry_where}: install type {entry_kind!r} does not match plugin install type {kind!r}")
        elif entry_kind == DIRECT:
            validate_install_plan(entry_install, f"{entry_where}: install", errors)


def validate_registry(registry: dict) -> list[str]:
    errors: list[str] = []
    schema_version = registry.get("schema_version")
    if schema_version not in (1, 2):
        return [f"unsupported schema_version {schema_version!r}"]
    plugins = registry.get("plugins")
    if not isinstance(plugins, list):
        return ["plugins must be a list"]
    seen_ids: set[str] = set()
    for index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            errors.append(f"plugins[{index}]: must be an object")
            continue
        where = f"plugins[{index}]"
        plugin_id = str(plugin.get("id", "")).strip()
        if plugin_id in seen_ids:
            errors.append(f"{where}: duplicate plugin id {plugin_id!r}")
        seen_ids.add(plugin_id)
        validate_plugin(plugin, schema_version, where, errors)
    return errors


def sample(**overrides) -> dict:
    plugin = {
        "id": "sample-provider",
        "name": "Sample Provider",
        "description": "Adds sample provider support.",
        "author": "neilforest7",
        "repository": "https://github.com/neilforest7/cpa-plugin-sample-provider",
    }
    plugin.update(overrides)
    return plugin


SELF_CHECKS: list[tuple[str, dict, list[str]]] = [
    ("empty registry", {"schema_version": 1, "plugins": []}, []),
    ("minimal plugin", {"schema_version": 1, "plugins": [sample()]}, []),
    ("bad schema_version", {"schema_version": 3, "plugins": []}, ["unsupported schema_version 3"]),
    (
        "blank required field",
        {"schema_version": 1, "plugins": [sample(description="  ")]},
        ["plugins[0]: missing required field description"],
    ),
    (
        "bad repository",
        {"schema_version": 1, "plugins": [sample(repository="https://github.com/a/b.git")]},
        ["plugins[0]: repository must be https://github.com/{owner}/{repo}"],
    ),
    (
        "v-prefixed version",
        {"schema_version": 1, "plugins": [sample(version="v0.1.0")]},
        ["plugins[0]: invalid plugin version 'v0.1.0'"],
    ),
    (
        "duplicate id",
        {"schema_version": 1, "plugins": [sample(), sample()]},
        ["plugins[1]: duplicate plugin id 'sample-provider'"],
    ),
    (
        "direct install on schema 1",
        {"schema_version": 1, "plugins": [sample(version="0.1.0", install={"type": "direct"})]},
        [
            "plugins[0]: direct install requires schema_version 2",
            "plugins[0]: install: direct install requires at least one artifact",
        ],
    ),
    (
        "direct artifact rules",
        {
            "schema_version": 2,
            "plugins": [
                sample(
                    version="0.1.0",
                    install={
                        "type": "direct",
                        "artifacts": [
                            {
                                "goos": "macos",
                                "goarch": "aarch64",
                                "url": "https://example.com/a.zip?token=secret",
                                "sha256": "abc",
                            }
                        ],
                    },
                )
            ],
        },
        [
            "plugins[0]: install: artifacts[0]: artifact url contains sensitive query parameter",
            "plugins[0]: install: artifacts[0]: invalid sha256",
        ],
    ),
]


def self_check() -> int:
    failures = 0
    for name, registry, expected in SELF_CHECKS:
        actual = validate_registry(registry)
        if actual != expected:
            failures += 1
            print(f"self-check {name}: expected {expected}, got {actual}", file=sys.stderr)
    if failures:
        print(f"self-check: {failures}/{len(SELF_CHECKS)} case(s) failed", file=sys.stderr)
        return 1
    print(f"self-check: ok ({len(SELF_CHECKS)} cases)")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        return self_check()
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "registry.json")
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        print(f"{path}: {err}", file=sys.stderr)
        return 1
    errors = validate_registry(registry)
    if errors:
        print(f"{path}: {len(errors)} problem(s)", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    count = len(registry.get("plugins") or [])
    print(f"{path}: ok ({count} plugin{'s' if count != 1 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
