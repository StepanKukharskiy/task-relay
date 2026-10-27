// Controlled layout host; no installed browser claim.
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const {routeWire,connectCards,flowRows}=await import(path.resolve('extensions/chrome/map-wires.js'));
 const a={x:24,y:70,width:200,height:130},b={x:272,y:70,width:200,height:130};
 const adjacent=routeWire(a,b);assert(adjacent.path.includes(' C '));assert(adjacent.x>a.x+a.width&&adjacent.x<b.x);
 const reverse=routeWire(b,a);assert.equal(reverse.start.x,b.x);assert.equal(reverse.end.x,a.x+a.width);assert(reverse.y>=70&&reverse.y<=200,'Reverse connection uses facing sides, never a perimeter rail');
 const stacked=routeWire(a,{...a,y:250});assert(stacked.y>200&&stacked.y<250,'Vertical wire stays between cards');
 for(const wire of [adjacent,reverse,stacked,routeWire(a,{...b,x:768})]){assert.equal((wire.path.match(/ C /g)||[]).length,1);assert(!/ [LQ] /.test(wire.path),'Every connection is one cubic without rail segments');}
 const fanA=routeWire(a,b,{from:.28,to:.28}),fanB=routeWire(b,a,{from:.72,to:.72});assert.notEqual(fanA.y,fanB.y,'Opposing relations use separate ports');
 const cards=[{id:'a',column:0,lane:0},{id:'b',column:1,lane:0},{id:'caveat',column:1,lane:1},{id:'c',column:2,lane:0}];
 const wide=flowRows(cards,3);assert.equal(wide.get('caveat').column,wide.get('b').column);assert(wide.get('caveat').row>wide.get('b').row);assert.equal(wide.get('a').row,wide.get('c').row);
 const narrow=flowRows(cards,1);assert.equal(new Set([...narrow.values()].map(p=>p.row)).size,4);assert(narrow.get('c').row>narrow.get('caveat').row);assert([...narrow.values()].every(p=>p.column===1));
 class El{
  constructor(){this.children=[];this.attrs={};this.style={};this.classList={add(){}};this.isConnected=true;}
  append(...items){this.children.push(...items);}prepend(el){this.children.unshift(el);}replaceChildren(){this.children=[];}setAttribute(k,v){this.attrs[k]=String(v);}getAttribute(k){return this.attrs[k];}
  getBoundingClientRect(){return this.rect;}querySelectorAll(){return this.cards||[];}
 }
 let frame,resize,removed,disconnections=0;
 const doc={body:new El(),createElementNS(){return new El();},defaultView:{ResizeObserver:class{constructor(fn){resize=fn;}observe(){}disconnect(){disconnections++;}},MutationObserver:class{constructor(fn){removed=fn;}observe(){}disconnect(){disconnections++;}},requestAnimationFrame(fn){frame=fn;return 1;},cancelAnimationFrame(){}}};
 const grid=new El();grid.ownerDocument=doc;grid.rect={left:0,top:0,width:500,height:220};grid.cards=[a,b].map((r,i)=>{const el=new El();el.attrs['data-wire-id']='n'+i;el.rect={left:r.x,top:r.y,width:r.width,height:r.height};return el;});
 connectCards(grid,[{from:'n0',to:'n1',label:'qualifies',title:'Exact recorded relation'},{from:'missing',to:'n1',label:'invalid',title:'No endpoint'}]);frame();const svg=grid.children[0];assert.equal(svg.children.length,1,'Only resolvable recorded edges are drawn');assert.equal(svg.children[0].attrs['data-edge-from'],'n0');assert.equal(svg.children[0].children[0].textContent,'Exact recorded relation');assert.equal(svg.children[0].children[2].textContent,'qualifies');
 grid.cards[1].rect={left:24,top:250,width:200,height:130};grid.rect.height=430;resize();frame();assert(svg.children[0].children[1].attrs.d.includes('200'),'Resize recomputes actual card endpoints');
 // Exercise the actual responsive arrangement, not only its pure row projection.
 grid.attrs['data-flow-columns']='2';grid.clientWidth=390;doc.defaultView.getComputedStyle=()=>({paddingLeft:'24',paddingRight:'24',columnGap:'56'});
 grid.cards.forEach((card,i)=>{card.attrs['data-flow-column']=String(i);card.attrs['data-flow-lane']='0';});
 const branch=new El();branch.attrs={'data-wire-id':'branch','data-flow-column':'0','data-flow-lane':'1'};branch.rect={left:80,top:215,width:144,height:90};grid.cards.push(branch);
 resize();frame();assert.equal(grid.style.gridTemplateColumns,'repeat(1, minmax(0, 1fr))');assert.equal(branch.style.width,'72%');assert.equal(branch.style.gridRow,'2');assert.equal(grid.cards[1].style.gridRow,'3');
 grid.clientWidth=1000;resize();frame();assert.equal(grid.style.gridTemplateColumns,'repeat(2, minmax(0, 1fr))');assert.equal(branch.style.width,'');assert.equal(grid.cards[1].style.gridRow,'1');
 svg.isConnected=false;removed();assert.equal(disconnections,2,'Replacing an overlay releases observers even when its host stays connected');
 const expansion=new El();expansion.ownerDocument=doc;expansion.rect={left:0,top:0,width:1300,height:800};expansion.cards=[{left:1000,top:20,width:200,height:130},{left:24,top:250,width:1200,height:500}].map((rect,i)=>{const el=new El();el.rect=rect;el.attrs['data-wire-id']='v'+i;return el;});
 connectCards(expansion,[{from:'v0',to:'v1',expansion:true,label:'',title:'Expanded phase 5'}]);frame();const group=expansion.children[0].children[0];assert.equal(group.attrs['data-expansion-wire'],'true');const curve=group.children[1].attrs.d;assert(curve.startsWith('M 1100 150 C '),'Expansion exits the selected card bottom even at the far right');assert(curve.endsWith('1124 250'),'Expansion enters the outlined detail group top near its origin');
 expansion.isConnected=false;removed();assert.equal(disconnections,4);
 console.log(JSON.stringify({passed:true,scope:'Measured responsive wire endpoints, single-cubic facing handles, branch-aware responsive rows, exact connection labels, missing endpoints, resize and observer disposal',live_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
