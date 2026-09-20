const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildArgs, runProcess, parseResult, utf16Offset } = require('./runner');
let programDiagnostics;
const generations = new Map();

let output;
let codeLensEmitter;
const explanationCache = new Map();
const EXTENSION_ID = 'shipmblang';
const LEGACY_EXTENSION_IDS = ['shiplang', 'drip'];

function activate(context) {
  output = vscode.window.createOutputChannel('ShipMBLang');
  programDiagnostics = vscode.languages.createDiagnosticCollection('shipmblang');
  context.subscriptions.push(programDiagnostics, vscode.workspace.onDidChangeTextDocument(event => programDiagnostics.delete(event.document.uri)),
    vscode.workspace.onDidCloseTextDocument(document => { programDiagnostics.delete(document.uri); generations.delete(document.uri.toString()); }));
  codeLensEmitter = new vscode.EventEmitter();

  context.subscriptions.push(output, codeLensEmitter);
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.newProseProgram', async () => {
    const document = await vscode.workspace.openTextDocument({language: 'shipmblang',
      content: '"Start with total at 4, then add 8 to total and show total."\n'});
    await vscode.window.showTextDocument(document);
    return document;
  }));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.explainCurrentDiagnostic', explainCurrentDiagnostic));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.explainPastedError', explainPastedError));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.explainDiagnostic', explainDiagnosticCommand));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.compileNaturalProgram', compileNaturalProgram));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.runNaturalProgram', runNaturalProgram));
  context.subscriptions.push(vscode.commands.registerCommand('shipmblang.clarifyAndRun', answer => executeProgram('run', true, typeof answer === 'string' ? answer : undefined)));
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

async function compileNaturalProgram() { return executeProgram('compile'); }
async function runNaturalProgram() { return executeProgram('run'); }

async function executeProgram(mode, clarify = false, interpretation) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) { vscode.window.showWarningMessage('ShipMBLang needs an open editor.'); return; }
  if (!vscode.workspace.isTrusted) { vscode.window.showWarningMessage('Trust this workspace before running ShipMBLang.'); return; }
  const document = editor.document;
  const source = selectedOrWholeDocument(editor);
  const base = editor.selection.isEmpty ? 0 : document.offsetAt(editor.selection.start);
  const version = document.version;
  const key = document.uri.toString();
  const generation = (generations.get(key) || 0) + 1;
  generations.set(key, generation);
  const diagnostic = findDiagnosticAtCursor(document, editor.selection.active);
  try {
    if (clarify) {
      if (getConfigurationValue('pipeline', 'direct', document.uri) !== 'direct') {
        vscode.window.showWarningMessage('Clarify and Run requires the direct pipeline.'); return;
      }
      interpretation = interpretation === undefined ? await vscode.window.showInputBox({
        title: 'ShipMBLang: Clarify and Run',
        prompt: 'Restate the complete intended program in English. The compiler validates this answer against the original source.',
        ignoreFocusOut: true
      }) : interpretation;
      if (!interpretation || !interpretation.trim()) return;
      if (document.isClosed || document.version !== version || generations.get(key) !== generation) {
        vscode.window.showWarningMessage('Source changed while clarifying. Run Clarify and Run again for the current text.'); return;
      }
    }
    return await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
      title: `ShipMBLang: ${mode}`, cancellable: true }, async (_, token) => {
      const result = await callNaturalShipLang(mode, source, document,
        diagnostic ? diagnostic.message : '', diagnostic ? collectEditorContext(document, diagnostic.range.start.line) : '', token, interpretation);
      if (document.isClosed || document.version !== version || generations.get(key) !== generation) {
        output.appendLine('Source changed; discarded stale compiler feedback.');
        return undefined;
      }
      const diagnostics = result.diagnostics || (result.semantic_model && result.semantic_model.diagnostics) || [];
      const questions = (result.clarifications || []).map(q => ({ ...q, message: q.question, level: 'warning', code: 'clarification' }));
      programDiagnostics.set(document.uri, [...diagnostics, ...questions].map(item => {
        const span = item.span || item.source_span || { start: 0, end: 0 };
        const start = document.positionAt(base + utf16Offset(source, span.start));
        const end = document.positionAt(base + utf16Offset(source, Math.max(span.start || 0, span.end || 0)));
        const entry = new vscode.Diagnostic(new vscode.Range(start, end), item.message || String(item),
          item.level === 'warning' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error);
        entry.source = 'ShipMBLang'; entry.code = item.code;
        return entry;
      }));
      output.appendLine(`\nShipMBLang ${mode}`);
      if (mode === 'run' && result.runtime && typeof result.runtime.stdout === 'string') output.append(result.runtime.stdout);
      else if (mode === 'run' && typeof result.output === 'string') output.appendLine(result.output);
      else output.appendLine(JSON.stringify(result, null, 2));
      if (diagnostics.length || questions.length) output.appendLine(JSON.stringify({ diagnostics, clarifications: result.clarifications || [] }, null, 2));
      output.show(true);
      return result;
    });
  } catch (error) {
    output.appendLine(error.message); output.show(true);
    vscode.window.showErrorMessage(error.message);
    return undefined;
  }
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
    const pythonPath = getConfigurationValue('pythonPath', 'python', undefined);
    const projectRoot = resolveProjectRoot(getConfigurationValue('projectRoot', getLegacyConfigurationValue('dripRoot', ''), undefined));
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

async function callNaturalShipLang(mode, source, document, rawError = '', codeContext = '', token, interpretation) {
  const tmpDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'shipmblang-'));
  const sourceFile = path.join(tmpDir, 'program.shipmb');
  const errorFile = path.join(tmpDir, 'error.txt');
  const contextFile = path.join(tmpDir, 'context.txt');
  await fs.promises.writeFile(sourceFile, source, 'utf8');
  await fs.promises.writeFile(errorFile, rawError, 'utf8');
  await fs.promises.writeFile(contextFile, codeContext, 'utf8');

  try {
    const pythonPath = getConfigurationValue('pythonPath', 'python', document && document.uri);
    const projectRoot = resolveProjectRoot(getConfigurationValue('projectRoot', getLegacyConfigurationValue('dripRoot', ''), document && document.uri), document);
    const args = buildArgs(mode, sourceFile, workspaceRootForDocument(document), {
      pipeline: getConfigurationValue('pipeline', 'direct', document.uri),
      profile: getConfigurationValue('profile', 'general', document.uri),
      memory: getConfigurationValue('memory', false, document.uri), errorFile, contextFile, interpretation
    });
    const response = await runProcess(pythonPath, args, { cwd: projectRoot, token,
      timeoutMs: getConfigurationValue('timeoutMs', 30000, document.uri) });
    if (response.stderr.trim()) output.appendLine(response.stderr.trim());
    return parseResult(response);
  } finally {
    fs.promises.rm(tmpDir, { recursive: true, force: true }).catch(() => {});
  }
}

function getConfigurationValue(key, fallback, uri) {
  const value = vscode.workspace.getConfiguration(EXTENSION_ID, uri).get(key);
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

function resolveProjectRoot(configuredRoot, document) {
  if (configuredRoot && fs.existsSync(configuredRoot)) {
    return configuredRoot;
  }
  const workspace = (document && vscode.workspace.getWorkspaceFolder(document.uri)) || (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0]);
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
  return document.uri.scheme === 'file' ? path.dirname(document.uri.fsPath) : resolveProjectRoot('');
}

async function spawnShipLang(command, args, cwd, transform) {
  if (!vscode.workspace.isTrusted) throw new Error('Trust this workspace before running ShipMBLang.');
  const result = await runProcess(command, ['-X', 'utf8', ...args], { cwd });
  if (result.code !== 0) throw new Error(result.stderr || result.stdout || `ShipMBLang exited with code ${result.code}`);
  return transform(result.stdout);
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
