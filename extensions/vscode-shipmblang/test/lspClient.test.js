const { test } = require('node:test');
const assert = require('node:assert/strict');
const { encodeMessage, createParser } = require('../src/lspClient');

test('content-length frames survive a split read', () => {
  const seen = [];
  const push = createParser((message) => seen.push(message));
  const bytes = encodeMessage({ jsonrpc: '2.0', method: 'initialized', params: {} });
  push(bytes.subarray(0, 8));
  assert.equal(seen.length, 0);
  push(bytes.subarray(8));
  assert.equal(seen.length, 1);
  assert.equal(seen[0].method, 'initialized');
});

test('two messages in one chunk stay in order', () => {
  const seen = [];
  const push = createParser((message) => seen.push(message));
  const first = encodeMessage({ jsonrpc: '2.0', id: 1, result: { capabilities: {} } });
  const second = encodeMessage({ jsonrpc: '2.0', method: 'textDocument/publishDiagnostics', params: { uri: 'file:///a.shipmb', diagnostics: [] } });
  push(Buffer.concat([first, second]));
  assert.equal(seen.length, 2);
  assert.equal(seen[0].id, 1);
  assert.equal(seen[1].params.uri, 'file:///a.shipmb');
});
