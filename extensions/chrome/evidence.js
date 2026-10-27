// Deterministic source units: the model selects IDs; code extracts literals.
// Units cover every UTF-16 source character, including whitespace, exactly once.
export function sourceUnits(content){
  const units=[];let start=0;
  while(start<content.length){let end=Math.min(start+1000,content.length);if(end<content.length){const boundary=content.lastIndexOf('\n',end);if(boundary>start+350)end=boundary+1;if(/[\uD800-\uDBFF]/.test(content[end-1]))end--;}
    units.push({id:'e'+String(units.length+1).padStart(4,'0'),start,end,text:content.slice(start,end)});start=end;}
  return units;
}
export function evidence(content,row){
  if(Object.hasOwn(row,'source_ref')){if(typeof row.source_ref!=='string')throw Error('Invalid evidence reference');const unit=sourceUnits(content).find(u=>u.id===row.source_ref);if(!unit||!unit.text.trim())throw Error('Evidence reference is absent or empty in this source');return {start:unit.start,end:unit.end,quote:unit.text};}
  if(typeof row.quote!=='string'||!row.quote.trim()||row.quote.length>4000)throw Error('Invalid evidence quote');const start=content.indexOf(row.quote);if(start<0)throw Error('Map evidence is absent from this source');if(content.indexOf(row.quote,start+1)>=0)throw Error('Map evidence is ambiguous. Use a longer unique quote.');return {start,end:start+row.quote.length,quote:row.quote};
}
