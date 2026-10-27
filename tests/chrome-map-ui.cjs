// Controlled extension DOM fixture; no provider or installed-browser claim.
const assert=require('node:assert/strict'),path=require('node:path');
class Element{
 constructor(tag,doc){this.tagName=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.style={};this.clientWidth=800;this.clientHeight=430;this.scrollLeft=0;this.scrollTop=0;}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=[];if(this.ownerDocument.clampOnRemoval&&this.ownerDocument.mapRoot===this){const d=this.ownerDocument;d.scrollY=Math.min(d.scrollY,Math.max(0,(parseFloat(this.style.minHeight)||0)-d.viewportHeight));}this.append(...items);}
 getBoundingClientRect(){return {height:this.ownerDocument.renderedHeight||0};}
 setAttribute(k,v){this.attrs[k]=String(v);}getAttribute(k){return this.attrs[k]??null;}
 setPointerCapture(id){this.pointer=id;}closest(){return null;}
 focus(options){this.ownerDocument.focused=this;if(!options?.preventScroll){this.ownerDocument.scrollY=0;this.ownerDocument.scrollRequests.push('focus');}}
 scrollIntoView(){this.ownerDocument.scrollY=900;this.ownerDocument.scrollRequests.push('scrollIntoView');}
 set innerHTML(html){this.children=[];if(html.includes('<svg')){const svg=new Element('svg',this.ownerDocument);this.children.push(svg);for(const match of html.matchAll(/<g\s+([^>]+)>/g)){const el=new Element('g',this.ownerDocument);for(const a of match[1].matchAll(/(data-[a-z-]+)="([^"]*)"/g))el.setAttribute(a[1],a[2]);svg.children.push(el);}}}
 querySelector(selector){const attr=selector.match(/^\[([^=]+)="([^"]+)"\]$/);return walk(this).find(el=>attr?el.getAttribute(attr[1])===attr[2]:el.tagName===selector)||null;}
 querySelectorAll(selector){return walk(this).filter(el=>selector.split(',').some(s=>el.getAttribute(s.slice(1,-1))!==null));}
}
const walk=el=>[el,...el.children.flatMap(walk)],find=(root,text)=>walk(root).find(el=>el.tagName==='button'&&el.textContent===text);
(async()=>{
 const maps=await import(path.resolve('extensions/chrome/work-map.js'));
 const content='First trial.\nSecond trial.',capture={title:'Synthetic chronology',url:'',extracted_content:content,source_metadata:{captured_at:'2026-10-20T00:00:00Z',limitations:[]}};
 const map=await maps.createMap(capture,[{start:0,end:content.length,fragment:{nodes:[{key:'one',kind:'attempt',label:'First trial',status:'reported',quote:'First trial.'},{key:'two',kind:'attempt',label:'Second trial',status:'reported',quote:'Second trial.'}],edges:[{from:'two',to:'one',relation:'precedes',quote:content}]}}]);
 const doc={scrollY:360,scrollRequests:[],createElement:tag=>new Element(tag,doc)},root=new Element('div',doc),receipts=[];let fail=false;
 const persist=async receipt=>{if(fail)throw Error('Controlled session quota failure');receipts.push(receipt);};
 maps.renderMap(root,map,persist);assert.equal(receipts.length,0,'Rendering never accepts or saves a review');
 assert.equal(root.querySelectorAll('[data-node-id]').length,0,'Overview starts collapsed');
 const phase=root.querySelectorAll('[data-phase-id]')[0];phase.onclick();assert.equal(root.querySelectorAll('[data-node-id]').length,2);assert.equal(receipts.length,0,'Expanding a phase does not save');
 find(root,'Collapse phase').onclick();assert.equal(root.querySelectorAll('[data-node-id]').length,0);
 find(root,'Full graph').onclick();
 root.querySelectorAll('[data-node-id]').find(el=>el.getAttribute('data-node-id')===map.nodes[0].id).onclick();assert(walk(root).some(el=>el.tagName==='blockquote'&&el.textContent==='First trial.'));
 const before=structuredClone(map.edges[0]);await find(root,'Reverse chronology').onclick();assert.equal(map.edges[0].from,before.to);assert.equal(map.edges[0].to,before.from);assert.equal(receipts.length,1);assert.deepEqual(receipts[0].before,before);await maps.validateMap(map);
 root.querySelectorAll('[data-node-id]').find(el=>el.getAttribute('data-node-id')===map.nodes[0].id).onclick();assert(!find(root,'All connections').hidden);find(root,'Close details').onclick();assert(find(root,'All connections').hidden);
 root.querySelectorAll('[data-node-id]').find(el=>el.getAttribute('data-node-id')===map.nodes[0].id).onclick();const input=walk(root).find(el=>el.tagName==='textarea'),old=map.nodes[0].label;input.value='Edited label';fail=true;await find(root,'Keep label edit').onclick();assert.equal(map.nodes[0].label,old);assert(walk(root).some(el=>el.textContent==='Controlled session quota failure'));
 // Reverse failure restores the original edge instead of presenting an unsaved correction.
 const current=structuredClone(map.edges);await find(root,'Reverse chronology').onclick();assert.deepEqual(map.edges,current);fail=false;
 const viewport=walk(root).find(el=>el.className==='map-viewport');viewport.scrollLeft=120;viewport.onpointerdown({button:0,target:new Element('svg',doc),clientX:10,clientY:20,pointerId:1});viewport.onpointermove({clientX:50,clientY:30});assert.equal(viewport.scrollLeft,80);viewport.onpointerup();assert.equal(viewport.onpointermove,null);
 find(root,'Fit map').onclick();assert.equal(viewport.scrollLeft,0);assert.equal(viewport.scrollTop,0);assert(parseFloat(root.querySelector('svg').style.width)<=800);
 // Larger map exercises phase navigation and a reviewed edge crossing a collapsed boundary.
 const body=Array.from({length:10},(_,i)=>'Unique trial '+i+'.').join('\n'),large=await maps.createMap({...capture,extracted_content:body},[{start:0,end:body.length,fragment:{nodes:Array.from({length:10},(_,i)=>({key:'n'+i,kind:'attempt',label:'Trial '+i,status:'reported',quote:'Unique trial '+i+'.'})),edges:Array.from({length:9},(_,i)=>({from:'n'+i,to:'n'+(i+1),relation:'precedes',quote:'Unique trial '+i+'.'}))}}]);
 const largeBefore=JSON.stringify(large);maps.renderMap(root,large,persist);assert.equal(root.querySelectorAll('[data-phase-id]').length,3);assert.equal(root.querySelectorAll('[data-node-id]').length,0);
 root.querySelectorAll('[data-phase-id]')[0].onclick();assert.equal(root.querySelectorAll('[data-node-id]').length,4);assert.equal(doc.focused.getAttribute('aria-expanded'),'true');assert.equal(JSON.stringify(large),largeBefore);
 assert.equal(root.querySelectorAll('[data-expanded-phase]')[0].getAttribute('data-expanded-phase'),doc.focused.getAttribute('data-phase-id'),'Detail group identifies its selected phase');
 const boundary=large.nodes[3];root.querySelectorAll('[data-node-id]').find(el=>el.getAttribute('data-node-id')===boundary.id).onclick();assert(walk(root).some(el=>el.tagName==='summary'&&el.textContent.includes('Trial 4')),'Outside-phase evidence remains inspectable');
 assert.equal(doc.scrollY,360,'Selecting nodes and phases keeps the viewport where it was');assert.deepEqual(doc.scrollRequests,[]);
 let prevented=false;root.querySelectorAll('[data-node-id]')[0].onkeydown({key:' ',preventDefault(){prevented=true;}});assert(prevented);assert.equal(doc.scrollY,360,'Space selects a node without scrolling the page');
 assert(walk(root).some(el=>el.tagName==='button'&&el.textContent==='→ Phase 2 · precedes'));
 find(root,'→ Phase 2 · precedes').onclick();assert(root.querySelectorAll('[data-phase-id]')[1].getAttribute('aria-expanded')==='true');assert(root.querySelectorAll('[data-node-id]').some(el=>el.getAttribute('data-node-id')===large.nodes[4].id));
 assert.equal(root.querySelectorAll('[data-expanded-phase]')[0].getAttribute('data-expanded-phase'),root.querySelectorAll('[data-phase-id]')[1].getAttribute('data-phase-id'),'Cross-phase navigation retargets the detail group');
 assert.equal(doc.scrollY,360,'Cross-phase navigation does not move the viewport');
 root.querySelectorAll('[data-node-id]')[0].onclick();const edit=walk(root).find(el=>el.tagName==='textarea');edit.value='Reviewed trial label';await find(root,'Keep label edit').onclick();assert.equal(large.nodes[4].label,'Reviewed trial label');await maps.validateMap(large);assert.equal(root.querySelectorAll('[data-phase-id]')[1].getAttribute('aria-expanded'),'true');
 find(root,'Overview').onclick();assert.equal(root.querySelectorAll('[data-phase-id]').length,3);find(root,'Full graph').onclick();assert.equal(root.querySelectorAll('[data-node-id]').length,10);
 maps.renderMap(root,{...large,nodes:[],edges:[]});assert(walk(root).some(el=>el.textContent==='No supported nodes in this map.'));
 assert.deepEqual(doc.scrollRequests,[],'Map interactions never request automatic scrolling');assert.equal(doc.scrollY,360);
 // Browser scroll-range clamping is distinct from an explicit scroll request.
 // Simulate replacing a tall map near its bottom with a much shorter phase.
 const clampDoc={scrollY:560,scrollRequests:[],renderedHeight:1000,viewportHeight:400,createElement:tag=>new Element(tag,clampDoc)},clampRoot=new Element('div',clampDoc);clampDoc.mapRoot=clampRoot;
 maps.renderMap(clampRoot,large);clampRoot.querySelectorAll('[data-phase-id]')[0].onclick();clampDoc.clampOnRemoval=true;
 clampRoot.querySelectorAll('[data-phase-id]')[1].onclick();assert.equal(clampDoc.scrollY,560,'Replacing the host never temporarily reduces its scroll range');assert.equal(clampRoot.style.minHeight,'1000px');
 clampDoc.renderedHeight=700;clampRoot.querySelectorAll('[data-phase-id]')[2].onclick();assert.equal(clampDoc.scrollY,560,'A shorter phase keeps the previous workspace extent');assert.equal(clampRoot.style.minHeight,'1000px');
 find(clampRoot,'Collapse phase').onclick();assert.equal(clampDoc.scrollY,560,'Collapse retains space and focuses without scrolling');assert.deepEqual(clampDoc.scrollRequests,[]);
 clampDoc.clampOnRemoval=false;maps.renderMap(clampRoot,large);assert.equal(clampRoot.style.minHeight,'','Opening a fresh map does not inherit another view’s height reservation');
 console.log(JSON.stringify({passed:true,scope:'Actual map renderer with controlled DOM: collapsed overview, expansion/focus/collapse, cross-phase navigation/evidence, label edits, explicit chronology receipt, failed-save rollback, full graph, pan and fit',live_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
