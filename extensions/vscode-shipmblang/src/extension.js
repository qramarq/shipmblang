const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

let output;
let codeLensEmitter;
const explanationCache = new Map();
const EXTENSION_ID = 'shipmblang';
const LEGACY_EXTENSION_IDS = ['shiplang', 'drip'];

function activate(context) {
  output = vscode.window.createOutputChannel('ShipMBLang');
  codeLensEmitter = new vscode.EventEmitter();

  context.subscriptions.push(output, codeLensEmitter);
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.explainCurrentDiagnostic', explainCurrentDiagnostic));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.explainPastedError', explainPastedError));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.explainDiagnostic', explainDiagnosticCommand));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.compileNaturalProgram', compileNaturalProgram));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.runNaturalProgram', runNaturalProgram));
  context.subscriptions.push(vscode.commands.registerCommand('shiplang.explainCurrentDiagnostic', explainCurrentDiagnostic));
  context.subscriptions.push(vscode.commands.registerCommand('shiplang.explainPastedError', explainPastedError));
  context.subscriptions.push(vscode.commands.registerCommand('shiplang.explainDiagnostic', explainDiagnosticCommand));
  context.subscriptions.push(vscode.commands.registerCommand('shiplang.compileNaturalProgram', compileNaturalProgram));
  context.subscriptions.push(vscode.commands.registerCommand('shiplang.runNaturalProgram', runNaturalProgram));
  context.subscriptions.push(vscode.commands.registerCommand('drip.explainCurrentDiagnostic', explainCurrentDiagnostic));
  context.subscriptions.push(vscode.commands.registerCommand('drip.explainPastedError', explainPastedError));
  context.subscriptions.push(vscode.commands.registerCommand('drip.explainDiagnostic', explainDiagnosticCommand));
  context.subscriptions.push(vscode.languages.registerCodeActionsProvider({ scheme: 'file' }, new ShipLangCodeActionProvider(), {
    providedCodeActionKinds: [vscode.CodeActionKind.QuickFix]
  }));
  context.subscriptions.push(vscode.languages.registerCodeLensProvider({ scheme: 'file' }, new ShipLangCodeLensProvider()));
  context.subscriptions.push(vscode.languages.registerHoverProvider({ scheme: 'file' }, new ShipLangHoverProvider()));
  context.subscriptions.push(vscode.languages.onDidChangeDiagnostics(() => codeLensEmitter.fire()));

  context.workspaceState.update('shipmblang.extensionPath', context.extensionPath);
}

function deactivate() {}

class ShipLangCodeActionProvider {
  provideCodeActions(document, range, context) {
    return context.diagnostics.map((diagnostic) => {
      const action = new vscode.CodeAction('Explain with ShipMBLang', vscode.CodeActionKind.QuickFix);
      action.command = {
        command: 'shipmblang.explainDiagnostic',
        title: 'Explain with ShipMBLang',
        arguments: [document.uri, diagnostic]
      };
      return action;
    });
  }
}

class ShipLangCodeLensProvider {
  get onDidChangeCodeLenses() {
    return codeLensEmitter.event;
  }

  provideCodeLenses(document) {
    const diagnostics = vscode.languages.getDiagnostics(document.uri);
    return diagnostics.map((diagnostic) => {
      const title = explanationCache.has(cacheKey(document.uri, diagnostic.range.start.line))
        ? 'ShipMBLang: show explanation'
        : 'ShipMBLang: explain';
      return new vscode.CodeLens(diagnostic.range, {
        title,
        command: 'shipmblang.explainDiagnostic',
        arguments: [document.uri, diagnostic]
      });
    });
  }
}

class ShipLangHoverProvider {
  provideHover(document, position) {
    const diagnostics = vscode.languages.getDiagnostics(document.uri)
      .filter((diagnostic) => diagnostic.range.contains(position));
    if (diagnostics.length === 0) {
      return undefined;
    }

    const key = cacheKey(document.uri, diagnostics[0].range.start.line);
    const cached = explanationCache.get(key);
    const commandUri = vscode.Uri.parse(`command:shipmblang.explainDiagnostic?${encodeURIComponent(JSON.stringify([document.uri, diagnostics[0]]))}`);
    const md = new vscode.MarkdownString('', true);
    md.isTrusted = true;
    if (cached) {
      md.appendMarkdown(`**ShipMBLang**\n\n${cached}`);
    } else {
      md.appendMarkdown(`[Explain with ShipMBLang](${commandUri})`);
    }
    return new vscode.Hover(md, diagnostics[0].range);
  }
}

async function explainCurrentDiagnostic() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage('ShipMBLang needs an open editor.');
    return;
  }
  const diagnostic = findDiagnosticAtCursor(editor.document, editor.selection.active);
  if (!diagnostic) {
    vscode.window.showWarningMessage('No diagnostic found at the cursor.');
    return;
  }
  await explainDiagnostic(editor.document, diagnostic);
}

async function explainPastedError() {
  const editor = vscode.window.activeTextEditor;
  const rawError = await vscode.window.showInputBox({
    title: 'ShipMBLang: paste raw error',
    prompt: 'Paste a runtime error, compiler warning, or stack trace.',
    ignoreFocusOut: true
  });
  if (!rawError) {
    return;
  }
  const document = editor ? editor.document : undefined;
  const line = editor ? editor.selection.active.line : 0;
  const codeContext = document ? collectEditorContext(document, line) : '';
  await runAndShowShipLang(rawError, codeContext, document, line);
}

async function compileNaturalProgram() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage('ShipMBLang needs an open editor.');
    return;
  }
  const source = selectedOrWholeDocument(editor);
  await vscode.window.withProgress({
    location: vscode.ProgressLocation.Window,
    title: 'ShipMBLang is compiling the natural program...'
  }, async () => {
    const compiled = await callNaturalShipLang('compile', source, editor.document);
    output.appendLine('');
    output.appendLine('ShipMBLang Core');
    output.appendLine(compiled);
    output.show(true);
  });
}

async function runNaturalProgram() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage('ShipMBLang needs an open editor.');
    return;
  }
  const source = selectedOrWholeDocument(editor);
  const diagnostic = findDiagnosticAtCursor(editor.document, editor.selection.active);
  const rawError = diagnostic ? diagnostic.message : '';
  const codeContext = diagnostic ? collectEditorContext(editor.document, diagnostic.range.start.line) : '';
  await vscode.window.withProgress({
    location: vscode.ProgressLocation.Window,
    title: 'ShipMBLang is running the natural program...'
  }, async () => {
    const result = await callNaturalShipLang('run', source, editor.document, rawError, codeContext);
    output.appendLine('');
    output.appendLine('ShipMBLang Run');
    output.appendLine(result);
    output.show(true);
    vscode.window.showInformationMessage(shorten(result));
  });
}

async function explainDiagnosticCommand(uri, diagnostic) {
  const document = await vscode.workspace.openTextDocument(uri);
  await explainDiagnostic(document, diagnostic);
}

async function explainDiagnostic(document, diagnostic) {
  const line = diagnostic.range.start.line;
  const rawError = diagnostic.message;
  const codeContext = collectEditorContext(document, line);
  await runAndShowShipLang(rawError, codeContext, document, line);
}

async function runAndShowShipLang(rawError, codeContext, document, zeroBasedLine) {
  await vscode.window.withProgress({
    location: vscode.ProgressLocation.Window,
    title: 'ShipMBLang is explaining the error...'
  }, async () => {
    const explanation = await callPrinturf(rawError, codeContext);
    if (document) {
      explanationCache.set(cacheKey(document.uri, zeroBasedLine), explanation);
      codeLensEmitter.fire();
    }
    output.appendLine('');
    output.appendLine('ShipMBLang');
    output.appendLine(explanation);
    output.show(true);
    vscode.window.showInformationMessage(shorten(explanation));
  });
}

function findDiagnosticAtCursor(document, position) {
  const diagnostics = vscode.languages.getDiagnostics(document.uri);
  return diagnostics.find((diagnostic) => diagnostic.range.contains(position))
    || diagnostics.find((diagnostic) => diagnostic.range.start.line === position.line)
    || diagnostics[0];
}

function collectEditorContext(document, zeroBasedLine) {
  const radius = getConfigurationValue('contextRadius', 8);
  const start = Math.max(0, zeroBasedLine - radius);
  const end = Math.min(document.lineCount - 1, zeroBasedLine + radius);
  const lines = [`--- ${document.uri.fsPath} ---`];
  for (let line = start; line <= end; line += 1) {
    const marker = line === zeroBasedLine ? '>' : ' ';
    lines.push(`${marker} ${line + 1}: ${document.lineAt(line).text}`);
  }
  return lines.join('\n');
}

function selectedOrWholeDocument(editor) {
  const selection = editor.selection;
  if (!selection.isEmpty) {
    return editor.document.getText(selection);
  }
  return editor.document.getText();
}

async function callPrinturf(rawError, codeContext) {
  const tmpDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'shipmblang-'));
  const errorFile = path.join(tmpDir, 'error.txt');
  const contextFile = path.join(tmpDir, 'context.txt');
  await fs.promises.writeFile(errorFile, rawError, 'utf8');
  await fs.promises.writeFile(contextFile, codeContext, 'utf8');

  try {
    const pythonPath = getConfigurationValue('pythonPath', 'python');
    const projectRoot = resolveProjectRoot(getConfigurationValue('projectRoot', getLegacyConfigurationValue('dripRoot', '')));
    const args = ['-m', 'shipmblang', 'printurf', '--error-file', errorFile, '--context-file', contextFile];
    const checkpoint = getConfigurationValue('checkpoint', '');
    const tokenizer = getConfigurationValue('tokenizer', '');
    const device = getConfigurationValue('device', 'cpu');
    if (checkpoint) {
      args.push('--checkpoint', checkpoint);
    }
    if (tokenizer) {
      args.push('--tokenizer', tokenizer);
    }
    if (device) {
      args.push('--device', device);
    }

    return await spawnShipLang(pythonPath, args, projectRoot, extractExplanation);
  } finally {
    fs.promises.rm(tmpDir, { recursive: true, force: true }).catch(() => {});
  }
}

async function callNaturalShipLang(mode, source, document, rawError = '', codeContext = '') {
  const tmpDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'shipmblang-'));
  const sourceFile = path.join(tmpDir, 'program.shipmb');
  const errorFile = path.join(tmpDir, 'error.txt');
  const contextFile = path.join(tmpDir, 'context.txt');
  await fs.promises.writeFile(sourceFile, source, 'utf8');
  await fs.promises.writeFile(errorFile, rawError, 'utf8');
  await fs.promises.writeFile(contextFile, codeContext, 'utf8');

  try {
    const pythonPath = getConfigurationValue('pythonPath', 'python');
    const projectRoot = resolveProjectRoot(getConfigurationValue('projectRoot', getLegacyConfigurationValue('dripRoot', '')));
    const args = ['-m', 'shipmblang', mode, '--file', sourceFile, '--root', workspaceRootForDocument(document)];
    if (mode === 'run') {
      args.push('--error-file', errorFile, '--context-file', contextFile);
    }
    return await spawnShipLang(pythonPath, args, projectRoot, (stdout) => stdout.trim() || 'ShipLang produced no output.');
  } finally {
    fs.promises.rm(tmpDir, { recursive: true, force: true }).catch(() => {});
  }
}

function getConfigurationValue(key, fallback) {
  const value = vscode.workspace.getConfiguration(EXTENSION_ID).get(key);
  if (value !== undefined && value !== '') {
    return value;
  }
  return getLegacyConfigurationValue(key, fallback);
}

function getLegacyConfigurationValue(key, fallback) {
  for (const id of LEGACY_EXTENSION_IDS) {
    const value = vscode.workspace.getConfiguration(id).get(key);
    if (value !== undefined && value !== '') {
      return value;
    }
  }
  return fallback;
}

function resolveProjectRoot(configuredRoot) {
  if (configuredRoot && fs.existsSync(configuredRoot)) {
    return configuredRoot;
  }
  const workspace = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  if (workspace && fs.existsSync(path.join(workspace.uri.fsPath, 'shipmblang', '__main__.py'))) {
    return workspace.uri.fsPath;
  }
  const devRoot = path.resolve(__dirname, '..', '..', '..');
  if (fs.existsSync(path.join(devRoot, 'shipmblang', '__main__.py'))) {
    return devRoot;
  }
  return workspace ? workspace.uri.fsPath : process.cwd();
}

function workspaceRootForDocument(document) {
  const folder = vscode.workspace.getWorkspaceFolder(document.uri);
  if (folder) {
    return folder.uri.fsPath;
  }
  return path.dirname(document.uri.fsPath);
}

function spawnShipLang(command, args, cwd, transform) {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(command, args, { cwd, windowsHide: true });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(stderr || stdout || `ShipMBLang exited with code ${code}`));
        return;
      }
      resolve(transform(stdout));
    });
  });
}

function extractExplanation(stdout) {
  const lines = stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const contract = lines.find((line) => /^Error:\s/i.test(line) && /\bCause:\s/i.test(line) && /\bFix:\s/i.test(line));
  return contract || lines[lines.length - 1] || 'Error: No explanation was returned. Cause: ShipMBLang produced empty output. Fix: Check the ShipMBLang runtime configuration.';
}

function cacheKey(uri, zeroBasedLine) {
  return `${uri.toString()}#${zeroBasedLine}`;
}

function shorten(text) {
  return text.length <= 220 ? text : `${text.slice(0, 217)}...`;
}

module.exports = { activate, deactivate };
