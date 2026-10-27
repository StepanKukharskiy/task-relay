// Presentation only: recorded identities, no provider inference or network access.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {operationVisual,operationIcon}=require('../task_relay/assets/companion-workflow.js');
const rows=JSON.parse(fs.readFileSync(process.argv[2],'utf8')).operations;
for(const r of rows){const v=operationVisual(r.id);assert.notEqual(v.kind,'operation',r.id);if(v.logo){if(['higgsfield','runway'].includes(v.logo)){const png=fs.readFileSync('task_relay/assets/node-icons/'+v.logo+'.png');assert.equal(png.subarray(1,4).toString(),'PNG');continue;}const svg=fs.readFileSync('task_relay/assets/node-icons/'+v.logo+'.svg','utf8');assert.match(svg,/<svg/);assert.doesNotMatch(svg,/<script|<image|<foreignObject|onload=|href=/i);}}
assert.equal(operationVisual('blender.scene').logo,'blender');
assert.equal(operationVisual('rhino.grasshopper').logo,'rhinoceros');
assert.equal(operationVisual('web.sources.prepared.codex').label,'Codex search');
assert.equal(operationVisual('web.sources.prepared').logo,'googlegemini');
assert.equal(operationVisual('images.pptx').kind,'slides');
assert.equal(operationVisual('images.crop').kind,'crop');
assert.equal(operationVisual({operation:'model',objective:'Use Gemini to summarise',tools:['browser']}).logo,undefined);
assert.equal(operationVisual({operation:'model',backend:{type:'gemini-files'}}).logo,'googlegemini');
assert.equal(operationVisual('future.unknown').kind,'operation');
class E{constructor(tag){this.tag=tag;this.attrs={};this.children=[];}setAttribute(k,v){this.attrs[k]=v;}append(v){this.children.push(v);}replaceChildren(...v){this.children=v;}}
global.document={createElement:t=>new E(t),createElementNS:(_,t)=>new E(t)};
const brand=operationIcon('blender.scene');assert.equal(brand.children[0].src,'node-icons/blender.svg');assert.equal(brand.attrs['aria-hidden'],'true');
brand.children[0].onerror();assert.equal(brand.children[0].tag,'svg','Failed asset retains a useful mesh icon');
console.log(`Passed icon coverage for ${rows.length} registered operations, recorded provider identity, unknown fallback and unavailable local logo.`);
