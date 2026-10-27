// Global banner dismissal, including legacy URL-opening errors. No bridge calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('task_relay/assets/companion.js','utf8');
const begin=source.indexOf('function message('),end=source.indexOf('\nfunction text(',begin);
const element=()=>({children:[],hidden:true,classList:{toggle(){}},setAttribute(k,v){this[k]=v;},replaceChildren(...nodes){this.children=nodes;},append(...nodes){this.children.push(...nodes);}});
const feedback=element(),ctx=vm.createContext({$:()=>feedback,document:{createElement:element}});
vm.runInContext(source.slice(begin,end),ctx);
ctx.message('Not allowed to open URL',true);assert.equal(feedback.hidden,false);
assert.equal(feedback.children[0].textContent,'Not allowed to open URL');
assert.equal(feedback.children[1]['aria-label'],'Dismiss notification');
feedback.children[1].onclick();assert.equal(feedback.hidden,true);assert.equal(feedback.children.length,0);
ctx.message('New message');assert.equal(feedback.children.length,2);ctx.message('');assert.equal(feedback.hidden,true);
console.log('Notification dismissal passed: old error, clearing and subsequent notification.');
