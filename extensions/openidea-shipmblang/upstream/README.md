# Upstream change for OpenIDEA

`0001-plugin-languages-start-language-servers.patch` is a draft against
[OpenIDEA](https://github.com/l0ng-ai/openidea) tag `v0.1.33`
(`07609ef9c6cc6933aa39968b6a1f77d259adcbb3`). It is not an upstream pull
request.

Apply it from a checkout of that tag:

```sh
git apply /path/to/shipmblang/extensions/openidea-shipmblang/upstream/0001-plugin-languages-start-language-servers.patch
```

## What it changes

On 0.1.33, `PluginHost::languages` is merged only into the `languages` IPC
command (`src-tauri/src/commands/app.rs`). `LanguageRegistry::load` — used by
document detection and `LspManager` — reads built-in `languages/*.toml` plus
`<app-config>/languages/*.toml` and never sees plugin languages. A contributed
`.shipmb` file stays Plain Text, so `shipmblang lsp` is never spawned.

The patch adds `LanguageRegistry::set_plugin_languages` and
`Host::apply_plugin_languages`. Built-in and user-directory ids still win.
Open projects re-detect documents when the set changes, which closes and
reopens them on the language-server observer. The desktop shell publishes
plugin languages after the startup plugin load, after `plugin_list` (that call
is what loads dev plugins), and after install, enable, reload, uninstall, and
trust changes that unload dev plugins.

`tree-sitter` is not part of the change. `languages/dockerfile.toml` already
defines a language server without that key.

File icons stay on the hardcoded map in `src/ui/icons.tsx`. The plugin API in
`wit/plugin.wit` still cannot spawn a process, so a run action remains an
External Tool or a `.openidea/run.toml` configuration.

## Build status

This patch was not compiled. The OpenIDEA workspace sets `edition = "2024"`
and `rust-version = "1.96"`. The machine used to prepare it had Rust 1.83.
The behavior of the unmodified `openidea-server` 0.1.33 binary is what the
ShipMBLang docs describe.
