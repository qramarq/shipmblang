import test from 'node:test';
import assert from 'node:assert/strict';
import { createNote, createWriter, decodeNotes } from '../src/model.ts';
import { runNote, serviceUrl, terminalText } from '../src/compiler.ts';
import snapshot from '../src/compiler-snapshot.json' with { type: 'json' };

test('notes round-trip without losing quotations or Unicode', () => {
  const note = { ...createNote('one', 0), text: 'Present "café".\nShow 9.' };
  assert.deepEqual(decodeNotes(JSON.stringify([note])), [note]);
  assert.throws(() => decodeNotes('{broken'));
  assert.throws(() => decodeNotes(JSON.stringify([note, note])));
});
test('serialized saves cannot overwrite a newer edit with an older one', async () => {
  const saved = [];
  const write = createWriter(async text => { await new Promise(r => setTimeout(r, 5)); saved.push(text); });
  const note = createNote('one', 0);
  await Promise.all([write([note]), write([{ ...note, text: 'Show 5.' }])]);
  assert.equal(JSON.parse(saved.at(-1))[0].text, 'Show 5.');
});
test('failed saves can be retried', async () => {
  let calls = 0;
  const write = createWriter(async () => { if (++calls === 1) throw new Error('disk'); });
  await assert.rejects(write([]));
  await write([createNote('two', 1)]);
  assert.equal(calls, 2);
});
test('release connections require HTTPS and never allow embedded credentials', () => {
  assert.throws(() => serviceUrl('http://localhost:8765', false));
  assert.throws(() => serviceUrl('https://user:secret@example.com', false));
  assert.throws(() => serviceUrl('https://example.com/?token=secret', false));
  assert.equal(serviceUrl('https://example.com/', false), 'https://example.com');
  assert.equal(serviceUrl('http://localhost:8765', true), 'http://localhost:8765');
});
test('Run sends only this source and the pinned snapshot to the authenticated endpoint', async () => {
  const source = 'Pls show me the total of 2 and 3.';
  let sent;
  const response = { compiler: snapshot, ok: true, stdout: '5\n', diagnostics: [], clarifications: [] };
  const fetcher = async (url, options) => { sent = { url, options }; return Response.json(response); };
  const result = await runNote({ url: 'https://compiler.example.com', token: 'test-token' }, source, snapshot, false, fetcher);
  assert.equal(sent.url, 'https://compiler.example.com/v1/run');
  assert.equal(sent.options.headers.Authorization, 'Bearer test-token');
  assert.equal(sent.options.redirect, 'error');
  assert.deepEqual(JSON.parse(sent.options.body), { source, compiler: snapshot });
  assert.equal(terminalText(result), '5\n');
});
test('different snapshots and failed requests never look like successful runs', async () => {
  const connection = { url: 'https://compiler.example.com', token: 'test-token' };
  await assert.rejects(runNote(connection, 'Show 5.', snapshot, false,
    async () => Response.json({ compiler: { ...snapshot, commit: 'different' } })), /snapshot mismatch/);
  await assert.rejects(runNote(connection, 'Show 5.', snapshot, false,
    async () => Response.json({ error: 'Check access token' }, { status: 401 })), /Check access token/);
  await assert.rejects(runNote(connection, ' ', snapshot, false), /Write a program/);
});
test('compiler diagnostics are presented instead of invented output', () => {
  assert.equal(terminalText({ ok: false, stdout: '', compiler: snapshot, diagnostics: [{ message: 'Which value?' }], clarifications: [] }), 'Which value?');
});

test('Check sends source to the compile-only endpoint', async () => {
  let called;
  const fetcher = async (url, options) => {
    called = { url, body: JSON.parse(options.body) };
    return Response.json({ compiler: snapshot, ok: true, stdout: '', diagnostics: [], clarifications: [] });
  };
  await runNote({ url: 'https://compiler.example.com', token: 'test-token' }, 'Show 5.', snapshot, false, fetcher, 'check');
  assert.equal(called.url, 'https://compiler.example.com/v1/check');
  assert.equal(called.body.source, 'Show 5.');
  assert.equal(called.body.compiler.version, '0.5.0');
});
