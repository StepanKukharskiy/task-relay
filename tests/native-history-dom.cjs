// Native Edit-menu bridge: local text editing stays native; graph actions never dispatch work.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('task_relay/assets/companion.js','utf8');
const start=source.indexOf("native.event.listen('companion-edit-history'");
const end=source.indexOf("native.event.listen('companion-navigate'",start);
assert(start>0 && end>start);
let handler;const edits=[],graph=[];
const document={activeElement:{matches:()=>false},execCommand:action=>edits.push(action)};
const window={RelayNodeEditor:{history:action=>graph.push(action)}};
vm.runInNewContext(source.slice(start,end),{native:{event:{listen:(name,fn)=>{assert.equal(name,'companion-edit-history');handler=fn;}}},document,window});
handler({payload:'undo'});handler({payload:'redo'});assert.deepEqual(graph,['undo','redo']);
document.activeElement={matches:()=>true};handler({payload:'undo'});assert.deepEqual(edits,['undo']);
document.activeElement={matches:()=>false,isContentEditable:true};handler({payload:'redo'});assert.deepEqual(edits,['undo','redo']);
handler({payload:'run'});assert.equal(graph.length,2);assert.equal(edits.length,2);
document.activeElement=null;delete window.RelayNodeEditor.history;handler({payload:'undo'});
console.log('Native history bridge passed: canvas routing, text/contenteditable routing, invalid action and disposed editor.');
