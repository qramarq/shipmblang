const { test } = require('node:test');
const assert = require('node:assert/strict');
const { buildArgs, runProcess, parseResult, utf16Offset, commandFor } = require('../src/runner');
test('direct keeps literal paths, profile and JSON without legacy flags', () => {
 const args = buildArgs('run','C:/a space/\u4f8b.smb','C:/a space',{pipeline:'direct',profile:'general',errorFile:'e'});
 assert.ok(args.includes('C:/a space/\u4f8b.smb')); assert.ok(args.includes('general')); assert.ok(args.includes('json'));
 assert.equal(args.includes('--error-file'),false); assert.equal(args[args.indexOf('--memory')+1],'off');
});
test('legacy retains error context without profile', () => {
 const args=buildArgs('run','a.shipmb','.',{pipeline:'legacy',errorFile:'e',contextFile:'c'});
 assert.ok(args.includes('--error-file')); assert.equal(args.includes('--profile'),false);
});
test('nonzero structured diagnostics retained', () => {
 const value={status:'needs_clarification',diagnostics:[],clarifications:[{question:'Which value?'}]};
 assert.deepEqual(parseResult({code:1,stdout:JSON.stringify(value),stderr:''}),value);
});
test('stale Python CLI gives actionable upgrade guidance', () => {
 assert.throws(() => parseResult({code:2,stdout:'',stderr:'error: unrecognized arguments: --pipeline direct --memory off --profile general'}), /older ShipMBLang CLI.*shipmblang\.pythonPath.*reload VS Code/);
});
test('missing interpreter is actionable', async () => { await assert.rejects(runProcess('shipmblang-nonexistent-python',[]),/pythonPath/); });
test('Unicode and shell characters remain literal', async () => {
 const text='caf\u00e9 \ud83d\ude00; $(not-a-command)';
 const r=await runProcess(process.execPath,['-e','process.stdout.write(process.argv[1])',text]); assert.equal(r.stdout,text); assert.equal(r.code,0);
});
test('timeout terminates child', async () => { await assert.rejects(runProcess(process.execPath,['-e','setInterval(()=>{},1000)'],{timeoutMs:100}),/exceeded/); });
test('output bounded', async () => { await assert.rejects(runProcess(process.execPath,['-e','process.stdout.write("a".repeat(4096))'],{maxBytes:10}),/output exceeded/); });
test('cancellation stops child', async () => {
 const token={isCancellationRequested:false,onCancellationRequested(callback){const t=setTimeout(callback,50);return {dispose(){clearTimeout(t);}};}};
 await assert.rejects(runProcess(process.execPath,['-e','setInterval(()=>{},1000)'],{token}),/cancelled/);
});
test('Unicode spans and malformed results',()=>{assert.equal(utf16Offset('\ud83d\ude00ab',2),3); assert.throws(()=>parseResult({code:2,stdout:'',stderr:'missing package'}),/missing package/);});

test('new editor defaults select direct general prose compilation', () => {
 const args=buildArgs('run','paragraph.shipmb','.');
 assert.equal(args[args.indexOf('--pipeline')+1],'direct');
 assert.equal(args[args.indexOf('--profile')+1],'general');
 const manifest=require('../package.json');
 assert.equal(manifest.contributes.configuration.properties['shipmblang.pipeline'].default,'direct');
});

test('standalone executable replaces python -m and stays one argument', () => {
 const spec = commandFor('run', 'C:/a space/demo.shipmb', 'C:/a space', { executablePath: 'D:/tools/shipmblang.exe', pythonPath: 'python', interpretation: 'Show 1.' });
 assert.equal(spec.command, 'D:/tools/shipmblang.exe');
 assert.equal(spec.args[0], 'run');
 assert.equal(spec.args.includes('-m'), false);
 assert.equal(spec.args.includes('-X'), false);
 assert.equal(spec.args[spec.args.indexOf('--file') + 1], 'C:/a space/demo.shipmb');
 assert.equal(spec.args[spec.args.indexOf('--interpretation') + 1], 'Show 1.');
});
test('python remains the fallback when no executable is on PATH', () => {
 const spec = commandFor('compile', 'a.shipmb', '.', { pythonPath: 'python3', autoDetect: false, env: { PATH: '' } });
 assert.equal(spec.command, 'python3');
 assert.equal(spec.args[0], '-X');
 assert.equal(spec.args[2], '-m');
});
test('an executable on PATH is selected when executablePath is empty', () => {
 const fs = require('node:fs');
 const os = require('node:os');
 const path = require('node:path');
 const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'shipmb-bin-'));
 const name = process.platform === 'win32' ? 'shipmblang.exe' : 'shipmblang';
 fs.writeFileSync(path.join(directory, name), '');
 const spec = commandFor('run', 'a.shipmb', '.', { executablePath: '', pythonPath: 'python', env: { PATH: directory }, executableNames: [name] });
 assert.equal(spec.command, path.join(directory, name));
 assert.equal(spec.args[0], 'run');
});
test('explicit clarification remains one literal argument and direct only', () => {
 const interpretation='Show "hello". Then show 12; $(literal).';
 const args=buildArgs('run','p.shipmb','.',{interpretation});
 assert.equal(args[args.indexOf('--interpretation')+1],interpretation);
 assert.equal(buildArgs('run','p.shipmb','.',{pipeline:'legacy',interpretation}).includes('--interpretation'),false);
});
