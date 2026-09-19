const assert = require('node:assert/strict');
const vscode = require('vscode');
async function run() {
 const config=vscode.workspace.getConfiguration('shipmblang');
 for(const [key,value] of Object.entries({pythonPath:process.env.SHIPMB_TEST_PYTHON,projectRoot:process.env.SHIPMB_TEST_CWD,pipeline:'direct',profile:'general',memory:false})) await config.update(key,value,vscode.ConfigurationTarget.Global);
 const fs=require('node:fs'); const path=require('node:path');
 const file=path.join(process.env.SHIPMB_TEST_CWD,'editor program.smb');fs.writeFileSync(file,'Show 27.');
 const associated=await vscode.workspace.openTextDocument(vscode.Uri.file(file)); assert.equal(associated.languageId,'shipmblang');
 const extension=vscode.extensions.getExtension('shipmb.shipmblang'); assert.ok(extension); await extension.activate();
 const document=await vscode.workspace.openTextDocument({language:'shipmblang',content:'Let total be a mutable integer with value 27. Show total.'});
 await vscode.window.showTextDocument(document);
 const compiled=await vscode.commands.executeCommand('shipmblang.compileNaturalProgram'); assert.equal(compiled.status,'compiled'); assert.equal(compiled.target_code.profile,'general');
 const executed=await vscode.commands.executeCommand('shipmblang.runNaturalProgram'); assert.equal(executed.runtime.stdout,'27\n'); assert.equal(vscode.languages.getDiagnostics(document.uri).length,0);
 const invalid=await vscode.workspace.openTextDocument({language:'shipmblang',content:'Notes \ud83d\ude00\nShow missing.'}); const selectedEditor=await vscode.window.showTextDocument(invalid); selectedEditor.selection=new vscode.Selection(1,0,1,13);
 const rejected=await vscode.commands.executeCommand('shipmblang.compileNaturalProgram'); assert.notEqual(rejected.status,'compiled'); assert.ok(vscode.languages.getDiagnostics(invalid.uri).length>0); assert.equal(vscode.languages.getDiagnostics(invalid.uri)[0].range.start.line,1);
 const edit=new vscode.WorkspaceEdit();edit.replace(invalid.uri,new vscode.Range(1,0,1,13),'Show 27.'); await vscode.workspace.applyEdit(edit);
 assert.equal(vscode.languages.getDiagnostics(invalid.uri).length,0);
 console.log('SHIPMB_EDITOR_HOST_PASS: file association, compile, run27, selected spans, Problems, stale diagnostics cleared');
}
module.exports={run};
