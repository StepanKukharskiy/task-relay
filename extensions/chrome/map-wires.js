// Layout-only wires over responsive cards. Connections always come from the map.
// Same cubic construction used by flow editors: facing handle normals set
// control-point tangents. No rectangular rails or perimeter detours.
export function wireSides(a,b){
  const dx=b.x+b.width/2-a.x-a.width/2,dy=b.y+b.height/2-a.y-a.height/2;
  if(Math.abs(dx)>Math.abs(dy))return dx>=0?['right','left']:['left','right'];
  return dy>=0?['bottom','top']:['top','bottom'];
}
function handle(box,side,fraction){
  if(side==='left'||side==='right')return {x:box.x+(side==='right'?box.width:0),y:box.y+box.height*fraction};
  return {x:box.x+box.width*fraction,y:box.y+(side==='bottom'?box.height:0)};
}
export function routeWire(a,b,ports={}){
  const [fromSide,toSide]=ports.sides??wireSides(a,b),start=handle(a,fromSide,ports.from??.5),end=handle(b,toSide,ports.to??.5);
  const horizontal=fromSide==='left'||fromSide==='right',distance=horizontal?Math.abs(end.x-start.x):Math.abs(end.y-start.y),bend=Math.max(16,distance*.5);
  const normal={left:[-1,0],right:[1,0],top:[0,-1],bottom:[0,1]},from=normal[fromSide],to=normal[toSide];
  const c1={x:start.x+from[0]*bend,y:start.y+from[1]*bend},c2={x:end.x+to[0]*bend,y:end.y+to[1]*bend};
  return {path:`M ${start.x} ${start.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${end.x} ${end.y}`,x:(start.x+3*c1.x+3*c2.x+end.x)/8,y:(start.y+3*c1.y+3*c2.y+end.y)/8,start,end};
}
// Keep findings beneath their chronology anchor instead of inserting a card
// into the gap used by the main progression. Wrap whole columns at narrow widths.
export function flowRows(cards,columns){
  const ordered=[...new Set(cards.map(c=>c.column))].sort((a,b)=>a-b),rows=new Map();let row=1;
  for(let i=0;i<ordered.length;i+=columns){const band=ordered.slice(i,i+columns);for(const card of cards.filter(c=>band.includes(c.column)))rows.set(card.id,{column:band.indexOf(card.column)+1,row:row+card.lane});row+=1+Math.max(0,...cards.filter(c=>band.includes(c.column)).map(c=>c.lane));}
  return rows;
}
function arrangeCards(grid,win){
  if(!grid.getAttribute('data-flow-columns'))return;
  const style=win.getComputedStyle(grid),available=grid.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),gap=parseFloat(style.columnGap)||48;
  const columns=Math.max(1,Math.min(Number(grid.getAttribute('data-flow-columns')),Math.floor((available+gap)/(180+gap)))),cards=[...grid.querySelectorAll('[data-wire-id]')];
  grid.style.gridTemplateColumns=`repeat(${columns}, minmax(0, 1fr))`;
  const rows=flowRows(cards.map(card=>({id:card.getAttribute('data-wire-id'),column:Number(card.getAttribute('data-flow-column')),lane:Number(card.getAttribute('data-flow-lane'))})),columns);
  for(const card of cards){const cell=rows.get(card.getAttribute('data-wire-id')),branch=columns===1&&Number(card.getAttribute('data-flow-lane'))>0;card.style.gridColumn=String(cell.column);card.style.gridRow=String(cell.row);card.style.width=branch?'72%':'';card.style.justifySelf=branch?'end':'';}
}
export function connectCards(grid,connections){
  const doc=grid.ownerDocument,win=doc.defaultView;
  // DOM doubles and nonvisual hosts can still render the cards and inspect links.
  if(!doc.createElementNS||!win?.ResizeObserver)return;
  const ns='http://www.w3.org/2000/svg',svg=doc.createElementNS(ns,'svg');svg.classList.add('map-wires');svg.setAttribute('aria-label','Recorded connections');grid.prepend(svg);
  const draw=()=>{
    if(!grid.isConnected)return;
    arrangeCards(grid,win);svg.replaceChildren();const bounds=grid.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);
    const positions=new Map([...grid.querySelectorAll('[data-wire-id]')].map(el=>{const r=el.getBoundingClientRect();return [el.getAttribute('data-wire-id'),{x:r.left-bounds.left,y:r.top-bounds.top,width:r.width,height:r.height}];}));
    const usable=connections.filter(e=>positions.has(e.from)&&positions.has(e.to)),slots=new Map(),edgeSides=e=>e.expansion?['bottom','top']:wireSides(positions.get(e.from),positions.get(e.to));
    for(const edge of usable){const sides=edgeSides(edge);for(const [id,side] of [[edge.from,sides[0]],[edge.to,sides[1]]]){const key=id+':'+side;if(!slots.has(key))slots.set(key,[]);slots.get(key).push(edge);}}
    usable.forEach(edge=>{
      const a=positions.get(edge.from),b=positions.get(edge.to),sides=edgeSides(edge),fraction=(id,side,source)=>{const list=slots.get(id+':'+side);return list.length===1?(source ? .4 : .6):.28+.44*list.indexOf(edge)/(list.length-1);};
      let ports={from:fraction(edge.from,sides[0],true),to:fraction(edge.to,sides[1],false)};
      // In a single column, an indented branch leaves a clear vertical channel.
      // Use that channel for skip links instead of hiding a wire behind the card.
      if(Math.abs(a.x-b.x)<3&&Math.abs(a.width-b.width)<3&&['top','bottom'].includes(sides[0])){
        const top=Math.min(a.y+a.height,b.y+b.height),bottom=Math.max(a.y,b.y),between=[...positions.values()].filter(p=>p!==a&&p!==b&&p.y>=top&&p.y+p.height<=bottom);
        if(between.length){const free=[.1,.9,.2,.8].find(f=>{const x=a.x+a.width*f;return between.every(p=>x<p.x-6||x>p.x+p.width+6);});if(free!==undefined)ports={from:free,to:free};}
      }
      if(edge.expansion)ports={sides,from:.5,to:Math.max(.05,Math.min(.95,(a.x+a.width*.5+24-b.x)/b.width))};
      const wire=routeWire(a,b,ports),g=doc.createElementNS(ns,'g'),path=doc.createElementNS(ns,'path'),title=doc.createElementNS(ns,'title');
      g.setAttribute('data-edge-from',edge.from);g.setAttribute('data-edge-to',edge.to);
      if(edge.expansion)g.setAttribute('data-expansion-wire','true');
      title.textContent=edge.title;path.setAttribute('d',wire.path);path.setAttribute('fill','none');path.setAttribute('stroke','#8796fb');path.setAttribute('stroke-width','1.6');path.setAttribute('vector-effect','non-scaling-stroke');g.append(title,path);
      const label=doc.createElementNS(ns,'text');label.setAttribute('x',wire.x);label.setAttribute('y',wire.y-5);label.setAttribute('text-anchor','middle');label.textContent=edge.label;g.append(label);svg.append(g);
    });
  };
  let frame=null;const schedule=()=>{if(frame!==null)win.cancelAnimationFrame(frame);frame=win.requestAnimationFrame(()=>{frame=null;draw();});};
  const observer=new win.ResizeObserver(schedule);observer.observe(grid);for(const card of grid.querySelectorAll('[data-wire-id]'))observer.observe(card);
  // Each render replaces its own grid. Disconnect even when an ancestor is
  // removed. This watches only the extension view, never the captured website.
  const lifecycle=new win.MutationObserver(()=>{if(!grid.isConnected||!svg.isConnected){observer.disconnect();lifecycle.disconnect();if(frame!==null)win.cancelAnimationFrame(frame);}});
  lifecycle.observe(doc.body,{childList:true,subtree:true});schedule();
}
