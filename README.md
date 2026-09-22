# CLIProxyAPI Plugins

Plugin store source for CLIProxyAPI plugins by [@neilforest7](https://github.com/neilforest7).

This repository only serves `registry.json`. Plugin binaries, checksums, and release
notes live in each plugin's own repository, so shipping a plugin release never
requires a change here.

## Use

Add this repository as an extra store source next to the built-in official one:

```yaml
plugins:
  enabled: true
  dir: "/Users/<you>/.cli-proxy-api/plugins"   # must be an absolute writable path
  store-sources:
    - "https://raw.githubusercontent.com/neilforest7/cliproxyapi-plugins/main/registry.json"
```

The host binary must support dynamic plugins (`X-CPA-SUPPORT-PLUGIN: 1` on
management responses) and be started with a management key. Restart, then install:

```bash
curl -X POST -H "Authorization: Bearer $MANAGEMENT_KEY" \
  "http://localhost:8317/v0/management/plugin-store/<plugin-id>/install"
```

Add `?source=source-7bceaa0eb475` when the same plugin id also exists in another
store source. `plugins.enabled` is not flipped by an install; set it yourself.

## Registry format

`schema_version` is `1`. Every entry needs:

| field | rule |
| --- | --- |
| `id` | `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, unique across the file |
| `name` | display name |
| `description` | short, one line |
| `author` | GitHub handle or name |
| `repository` | exactly `https://github.com/{owner}/{repo}` |

Optional: `version` (display fallback only, no leading `v`), `logo`, `homepage`,
`license`, `tags`. `schema_version: 2` additionally allows `install.type: direct`
with explicit per-platform `artifacts` (`goos`, `goarch`, `url`, `sha256`, `size`).

```json
{
  "schema_version": 1,
  "plugins": [
    {
      "id": "sample-provider",
      "name": "Sample Provider",
      "description": "Adds sample provider support.",
      "author": "neilforest7",
      "repository": "https://github.com/neilforest7/cpa-plugin-sample-provider",
      "homepage": "https://github.com/neilforest7/cpa-plugin-sample-provider",
      "license": "MIT",
      "tags": ["provider"]
    }
  ]
}
```

## Release requirements

CLIProxyAPI resolves a plugin from its repository's latest GitHub release:

- Tag is `v<version>`, e.g. `v0.1.0`.
- One `checksums.txt` plus one zip per supported platform, named with the
  version without the leading `v`:

  ```text
  <id>_<version>_<goos>_<goarch>.zip
  checksums.txt
  ```

  ```text
  sample-provider_0.1.0_darwin_arm64.zip
  sample-provider_0.1.0_linux_amd64.zip
  sample-provider_0.1.0_windows_amd64.zip
  checksums.txt
  ```

- `checksums.txt` uses sha256sum format: `<sha256>  <zip-name>`.
- Each zip contains the dynamic library at the zip root, named after the plugin
  id: `<id>.dylib` (darwin), `<id>.so` (linux), `<id>.dll` (windows).

Keep one plugin per repository: the latest release of `repository` is the source
of truth for that plugin's version and assets.

## Validate

```bash
python3 scripts/validate_registry.py --self-check      # checks the validator itself
python3 scripts/validate_registry.py registry.json
```

`scripts/validate_registry.py` mirrors the upstream parser and validator in
`internal/pluginstore/registry.go`. CI runs both commands plus the `add-plugin.py`
self-check on every change to `registry.json`.

## Get a plugin listed

Once the plugin repository has a release, one command derives the entry from it and
updates `registry.json`:

```bash
python3 scripts/add-plugin.py neilforest7/mimo-cliproxyapi \
  --name "MiMo Provider" \
  --description "Xiaomi MiMo provider: Chat Completions executor, API-key auth and the V2.6 catalog." \
  --tags provider,xiaomi
```

It reads the repository's latest release and repository metadata through the GitHub API
(the `gh` CLI when available), takes the `id` from the release asset names
(`<id>_<version>_<goos>_<goarch>.zip`), and replaces any existing entry with the same id
or repository. `--dry-run` prints the entry without writing, `--self-check` verifies the
derivation rules. Pass `--description` whenever the plugin repository has no description
of its own.

The entry lands in `registry.json`; commit and push it (a pull request is equally fine).
The store reads the repository's latest release, so later versions only need a new tag in
the plugin repository.

## 中文速览

本仓库是 CLIProxyAPI 的插件商店源，只维护 `registry.json`，插件二进制放在各自的插件仓库
Release 里。把上面的 `store-sources` 配置加进 `config.yaml`，重启后用管理 API 安装。
新增插件：在 `registry.json` 追加一条，Release 打 `v<版本>` tag，资产命名
`<id>_<version>_<goos>_<goarch>.zip` 加 `checksums.txt`，zip 根目录放 `<id>.dylib|so|dll`。

## License

[MIT](LICENSE)
