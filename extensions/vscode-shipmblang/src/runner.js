const cp = require('node:child_process');

function buildArgs(mode, sourceFile, root, options = {}) {
  const pipeline = options.pipeline || 'legacy';
  const args = ['-X', 'utf8', '-m', 'shipmblang', mode, '--file', sourceFile,
    '--root', root, '--format', 'json', '--pipeline', pipeline,
    '--memory', options.memory ? 'on' : 'off'];
  if (pipeline === 'direct') args.push('--profile', options.profile || 'general');
  if (mode === 'run' && pipeline === 'legacy') {
    if (options.errorFile) args.push('--error-file', options.errorFile);
    if (options.contextFile) args.push('--context-file', options.contextFile);
  }
  return args;
}

function runProcess(command, args, { cwd, token, timeoutMs = 30000, maxBytes = 4 * 1024 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    if (token && token.isCancellationRequested) return reject(new Error('ShipMBLang operation cancelled.'));
    const child = cp.spawn(command, args, { cwd, windowsHide: true, shell: false,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } });
    let stdout = '', stderr = '', bytes = 0, failure;
    const stop = (message) => { failure = new Error(message); child.kill(); };
    const timer = setTimeout(() => stop(`ShipMBLang exceeded ${timeoutMs} ms.`), timeoutMs);
    const subscription = token && token.onCancellationRequested(() => stop('ShipMBLang operation cancelled.'));
    const cleanup = () => { clearTimeout(timer); if (subscription) subscription.dispose(); };
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    for (const [stream, append] of [[child.stdout, s => { stdout += s; }], [child.stderr, s => { stderr += s; }]]) {
      stream.on('data', chunk => {
        bytes += Buffer.byteLength(chunk);
        if (bytes > maxBytes) stop('ShipMBLang output exceeded the editor limit.');
        else append(chunk);
      });
    }
    child.on('error', error => { cleanup(); reject(new Error(`Cannot start ${command}: ${error.message}. Configure shipmblang.pythonPath with the Python environment containing ShipMBLang.`)); });
    child.on('close', code => { cleanup(); if (failure) reject(failure); else resolve({ code, stdout, stderr }); });
  });
}

function parseResult(result) {
  let program;
  try { program = JSON.parse(result.stdout); } catch (_) {
    throw new Error(result.stderr.trim() || result.stdout.trim() || `ShipMBLang exited with code ${result.code}.`);
  }
  if (!program || typeof program !== 'object' || Array.isArray(program)) throw new Error('ShipMBLang returned an invalid result.');
  if (result.code !== 0 && !Array.isArray(program.diagnostics) && !Array.isArray(program.clarifications)) {
    throw new Error(result.stderr.trim() || `ShipMBLang exited with code ${result.code}.`);
  }
  return program;
}

// Compiler spans count Unicode code points; VS Code positions count UTF-16 units.
function utf16Offset(source, offset) {
  return Array.from(source).slice(0, Math.max(0, Number.isInteger(offset) ? offset : 0)).join('').length;
}

module.exports = { buildArgs, runProcess, parseResult, utf16Offset };
