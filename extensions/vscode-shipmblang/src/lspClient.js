const { spawn } = require('node:child_process');

function encodeMessage(message) {
  const body = Buffer.from(JSON.stringify(message), 'utf8');
  const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'ascii');
  return Buffer.concat([header, body]);
}

function createParser(onMessage) {
  let buffer = Buffer.alloc(0);
  return function push(chunk) {
    buffer = Buffer.concat([buffer, Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)]);
    while (buffer.length) {
      const headerEnd = buffer.indexOf('\r\n\r\n');
      if (headerEnd < 0) return;
      const header = buffer.slice(0, headerEnd).toString('ascii');
      const match = /Content-Length:\s*(\d+)/i.exec(header);
      if (!match) {
        buffer = buffer.slice(headerEnd + 4);
        continue;
      }
      const length = Number(match[1]);
      const start = headerEnd + 4;
      if (buffer.length < start + length) return;
      const body = buffer.slice(start, start + length).toString('utf8');
      buffer = buffer.slice(start + length);
      onMessage(JSON.parse(body));
    }
  };
}

function startLanguageSession({ command, args, cwd, onDiagnostics, onExit, output }) {
  const child = spawn(command, args, {
    cwd,
    windowsHide: true,
    shell: false,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
  });
  let nextId = 1;
  const pending = new Map();
  let closed = false;
  const fail = (error) => {
    for (const waiter of pending.values()) waiter.reject(error);
    pending.clear();
  };
  const push = createParser((message) => {
    if (message && message.method === 'textDocument/publishDiagnostics' && message.params) {
      onDiagnostics(message.params);
    }
    if (message && message.id != null && pending.has(message.id)) {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message || 'Language server error'));
      else waiter.resolve(message.result);
    }
  });
  child.stdout.on('data', push);
  child.stderr.on('data', (chunk) => {
    if (output) output.appendLine(String(chunk).trimEnd());
  });
  child.on('error', (error) => {
    closed = true;
    fail(error);
    if (output) output.appendLine(`Language server did not start: ${error.message}`);
    if (onExit) onExit(error);
  });
  child.on('close', (code) => {
    closed = true;
    fail(new Error(`Language server exited (${code}).`));
    if (onExit) onExit(code);
  });

  function send(payload) {
    if (closed) throw new Error('Language server is not running.');
    child.stdin.write(encodeMessage(payload));
  }
  function request(method, params) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      try {
        send({ jsonrpc: '2.0', id, method, params });
      } catch (error) {
        pending.delete(id);
        reject(error);
      }
    });
  }
  function notify(method, params) {
    send({ jsonrpc: '2.0', method, params });
  }
  return {
    request,
    notify,
    stop() {
      if (closed) return;
      try { notify('shutdown', {}); } catch (_) { /* process already gone */ }
      try { notify('exit', {}); } catch (_) { /* process already gone */ }
      child.kill();
    },
  };
}

module.exports = { encodeMessage, createParser, startLanguageSession };
