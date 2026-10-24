const cp = require('node:child_process');

function buildArgs(mode, sourceFile, root, options = {}) {
  const pipeline = options.pipeline || 'direct';
  const args = ['-X', 'utf8', '-m', 'shipmblang', mode, '--file', sourceFile,
    '--root', root, '--format', 'json', '--pipeline', pipeline,
    '--memory', options.memory ? 'on' : 'off'];
  if (pipeline === 'direct') {
    args.push('--profile', options.profile || 'general');
    if (options.interpretation) args.push('--interpretation', options.interpretation);
  }
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
    if (/unrecognized arguments?:.*--(?:pipeline|memory|profile)/s.test(result.stderr)) {
      throw new Error('The configured Python environment has an older ShipMBLang CLI that does not support this VS Code extension. From the ShipMBLang repository root, run `python -m pip install --upgrade .` using the same Python configured in shipmblang.pythonPath, then reload VS Code. Details: ' + result.stderr.trim());
    }
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

const fs = require('node:fs');
const path = require('node:path');

function stripPythonModule(args) {
  const index = args.indexOf('shipmblang');
  if (index < 0) return args.slice();
  return args.slice(index + 1);
}

function findExecutable(env = process.env, names) {
  const list = names || (process.platform === 'win32'
    ? ['shipmblang.exe', 'shipmblang.cmd', 'shipmblang']
    : ['shipmblang']);
  const pathValue = env.PATH || env.Path || '';
  for (const directory of pathValue.split(path.delimiter)) {
    if (!directory) continue;
    for (const name of list) {
      const candidate = path.join(directory, name);
      try {
        if (fs.existsSync(candidate)) return candidate;
      } catch (_) { /* ignore unreadable PATH entries */ }
    }
  }
  return '';
}

function launchSpec(options = {}) {
  const executable = (options.executablePath || '').trim();
  const pythonPath = options.pythonPath || 'python';
  if (executable) return { command: executable, kind: 'executable' };
  if (options.autoDetect !== false) {
    const found = findExecutable(options.env || process.env, options.executableNames);
    if (found) return { command: found, kind: 'executable' };
  }
  return { command: pythonPath, kind: 'python' };
}

function commandFor(mode, sourceFile, root, options = {}) {
  const spec = launchSpec(options);
  const moduleArgs = buildArgs(mode, sourceFile, root, options);
  if (spec.kind === 'executable') return { command: spec.command, args: stripPythonModule(moduleArgs) };
  return { command: spec.command, args: moduleArgs };
}

function lspCommand(options = {}) {
  const spec = launchSpec(options);
  if (spec.kind === 'executable') return { command: spec.command, args: ['lsp'] };
  return { command: spec.command, args: ['-X', 'utf8', '-m', 'shipmblang', 'lsp'] };
}

module.exports = {
  buildArgs, runProcess, parseResult, utf16Offset, launchSpec, commandFor, lspCommand, findExecutable, stripPythonModule,
};
