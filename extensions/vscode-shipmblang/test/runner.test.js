const { test } = require('node:test');
const assert = require('node:assert/strict');
const { buildArgs, runProcess, parseResult, utf16Offset } = require('../src/runner');
test('direct keeps literal paths, profile and JSON without legacy flags', () => {
 const args = buildArgs('run','C:/a space/\u4f8b.smb','C:/a space',{pipeline:'direct',profile:'general',errorFile:'e'});
 assert.ok(args.includes('C:/a space/\u4f8b.smb')); assert.ok(args.includes('general')); assert.ok(args.includes('json'));
 assert.equal(args.includes('--error-file'),false); assert.equal(args[args.indexOf('--memory')+1],'off');
});
test('legacy retains error context without profile', () => {
 const args=buildArgs('run','a.shipmb','.',{errorFile:'e',contextFile:'c'});
 assert.ok(args.includes('--error-file')); assert.equal(args.includes('--profile'),false);
});
test('nonzero structured diagnostics retained', () => {
 const value={status:'needs_clarification',diagnostics:[],clarifications:[{question:'Which value?'}]};
 assert.deepEqual(parseResult({code:1,stdout:JSON.stringify(value),stderr:''}),value);
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
