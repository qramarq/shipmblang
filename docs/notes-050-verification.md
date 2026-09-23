# Notes 0.5.0 verification

Based on released language commit `4540943ee833d56241a389cd017dbad347a1e51b`.
The app runs bundled compiler `0.5.0`, source
`1d44e1d5f5feb4e1629008edc3a80c9246dcbca2`.

- Python suite: 126 tests run, 125 passed and one skipped on this host. Final focused
  notebook/service suite: 26 passed.
- Mobile: eight tests passed; TypeScript and Expo lint passed.
- Expo export: web, iOS and Android bundles passed. These are JavaScript/Hermes
  exports, not signed store binaries or physical-device QA.
- Built wheel and installed into a fresh virtual environment; tested from
  outside the checkout. Imported module came from site-packages. Quoted
  paragraphs printed `5` with the expected compiler version/commit.
- Installed notebook main launch displayed Check/Run/version and preserved an
  existing test database's program and legacy journal. CLI notebook help passed.
- Browser preview at 375×667: verified service connection, creating a separate
  quoted-paragraph starter, Check without execution, actual Run output `5`,
  terminal visibility, and note persistence after reload.
- At 375×367 with editor focused, guidance and terminal collapse to leave room
  for writing and all actions remain visible. This checks constrained layout;
  native keyboard and system text-size testing still require physical devices.
- Starters never execute automatically. Python tests cover independent notes,
  autosave, backup, stale-result labeling and preserved diary text.
- Notes rejects media/host-capability artifacts before Run. Standalone CLI
  media behavior is unchanged; implementation is deferred to the media plan.

## Launch

Desktop: run `notebook.cmd` from this checkout. It reuses the existing default
notes database. For an installed copy, run `python -m pip install .` from this
checkout, then `python -m shipmblang notebook` with that interpreter.

Mobile preview: in `apps/mobile`, run `npm ci` and `npm run web`. Start the
private compiler service and connect using the instructions in
[the mobile README](../apps/mobile/README.md). Both Check and Run need the
service; writing and autosave work locally. Older checkouts retain their own
versions and are not overwritten by this work.

The [media plan](notes-media-plan.md) covers future file workspaces, background
jobs, FFmpeg, owned VLC playback and HyperFrames rendering. No media UI or
store submission is included in this change.
