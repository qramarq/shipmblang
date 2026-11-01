# Changelog

## Unreleased

- OpenIDEA plugin in `extensions/openidea-shipmblang`. It associates `.shipmb`, `.smb`, and `.shiplang` and starts `shipmblang lsp`. Install steps are in [editors](docs/editors.md).

## 0.6.0

- Unicode sentence, word, and grapheme segmentation for CLI, LSP, and notebook text. Streaming chunks stay on a grapheme boundary. The bundled compiler snapshot is unchanged.
- Grammar `general-english-0.10` (#34). The consolidated language update includes the everyday English forms that compile under that grammar.
- Standalone executable and `shipmblang setup` (#35). One executable runs compile and run without a Python install. `shipmblang setup` installs missing Rust, FFmpeg (with ffprobe), VLC, and Ollama from their official sources. The artifact installer puts the executable on `PATH` and then runs setup.
- Two-way compiler sync (#36). GitHub Actions open pull requests so `shipmblang/_compiler/` and shipmblang-compiler stay aligned. This package release does not replace the bundled compiler snapshot; that snapshot still arrives through the compiler sync.
- Chat-room notebook, `shipmblang lsp`, and editor configs (#37). Saved notes open as rooms with a conversation timeline. `shipmblang lsp` is a stdio language server with diagnostics, hover, and compile/run commands. `docs/editors.md` has configs for VS Code, Cursor, Neovim, Vim, Emacs, Helix, Zed, Sublime Text, JetBrains, Notepad++, and Kate. `shipmblang --version` prints this package version.
