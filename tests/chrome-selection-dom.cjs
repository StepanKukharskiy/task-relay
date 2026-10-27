// Build an offline fixture for checking the serialized extractor with real DOM
// Range/Selection APIs in a browser. It uses only synthetic text, not an AI site.
const fs=require('node:fs'),path=require('node:path');
const output=process.argv[2];if(!output)throw Error('Supply the output HTML path');
const extractor=fs.readFileSync('extensions/chrome/extract.js','utf8').replace('export function','function');
const checks=String.raw`
const fixture=document.getElementById('fixture'),report=document.getElementById('report'),selection=window.getSelection();
const results=[];
function check(name,fn){try{fn();results.push({name,passed:true});}catch(error){results.push({name,passed:false,error:error.message});}}
function equal(actual,expected){if(actual!==expected)throw Error(JSON.stringify({actual,expected}));}
function select(html,start,end,startOffset=0,endOffset){fixture.innerHTML=html;selection.removeAllRanges();const range=document.createRange();const first=fixture.querySelector(start).firstChild,last=fixture.querySelector(end).firstChild;range.setStart(first,startOffset);range.setEnd(last,endOffset??last.length);selection.addRange(range);return range;}
function capture(){return taskRelayCapture(true);}
check('Visible paragraphs across hidden heading and Copy control',()=>{select('<p id="a">First paragraph</p><h4 class="sr-only">Hidden role</h4><button>Copy</button><p id="b">Second paragraph</p>','#a','#b');const result=capture();equal(result.selected_content,'First paragraph\nSecond paragraph');if(!result.source_metadata.limitations.some(s=>s.includes('were excluded')))throw Error('Missing filter coverage');});
check('Exact partial boundaries and inline formatting',()=>{select('<p id="a">prefix Kept <strong>bold</strong> tail suffix</p><span hidden>Invisible</span><p id="b">prefix End suffix</p>','#a','#b',7,10);equal(capture().selected_content,'Kept bold tail suffix\nprefix End');});
check('Hidden value identical to valid evidence is retained only at visible position',()=>{select('<p id="a">Keep repeated phrase</p><span style="display:none">repeated phrase</span><p id="b">More evidence</p>','#a','#b');equal(capture().selected_content,'Keep repeated phrase\nMore evidence');});
check('Visually rendered aria-hidden citations are readable',()=>{select('<p id="a">Evidence <span aria-hidden="true">[1]</span> <a inert>source</a></p>','#a','a');const native=selection.toString();equal(capture().selected_content,native);});
check('Visible forms are refused',()=>{select('<p id="a">Evidence</p><form><div id="b">Private draft</div></form>','#a','#b');if(!/input field/.test(capture().captureError))throw Error('Captured form');});
check('Editable fields are refused',()=>{select('<p id="a">Evidence</p><div contenteditable="" id="b">Private draft</div>','#a','#b');if(!/input field/.test(capture().captureError))throw Error('Captured editor');});
check('Boundary touching a form does not read its draft',()=>{select('<p id="a">Evidence</p><form><div id="b">Private draft</div></form>','#a','#b',0,0);equal(capture().selected_content,selection.toString());});
check('Hidden form does not poison visible excerpt',()=>{select('<p id="a">First</p><form style="display:none">Private draft</form><p id="b">Second</p>','#a','#b');equal(capture().selected_content,'First\nSecond');});
check('Only hidden selection is refused',()=>{select('<span hidden id="a">Hidden</span>','#a','#a');if(!capture().captureError)throw Error('Captured hidden text');});
check('Missing selection does not expand capture to page',()=>{selection.removeAllRanges();if(!/Select text/.test(capture().captureError))throw Error('Captured without selection');});
check('Oversize filtered selection is never truncated',()=>{select('<p id="a">'+ 'x'.repeat(300001)+'</p><span hidden>Hidden</span><p id="b">End</p>','#a','#b');if(!/nothing was truncated/.test(capture().captureError))throw Error('Captured oversize text');});
selection.removeAllRanges();fixture.replaceChildren();
const result={passed:results.every(row=>row.passed),checks:results.length,results,scope:'Real DOM selection with synthetic text; no installed extension or AI execution'};
report.textContent=JSON.stringify(result,null,2);document.title=result.passed?'Selection checks passed':'Selection checks FAILED';
`;
fs.mkdirSync(path.dirname(output),{recursive:true});
fs.writeFileSync(output,`<!doctype html><meta charset="utf-8"><title>Selection checks</title><style>.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}body{font:16px system-ui}pre{white-space:pre-wrap}</style><h1>Task Relay selection checks</h1><div id="fixture"></div><pre id="report">Running…</pre><script>(()=>{const location={hostname:'fixture.example.test',href:'https://fixture.example.test/article'};${extractor}\n${checks}})();</script>`);
console.log(JSON.stringify({fixture:output,scope:'Generated real-DOM fixture; not yet executed'}));
