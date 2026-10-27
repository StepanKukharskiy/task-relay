// Read an exported, non-overlapping website log window from stdin; emit aggregate CSV.
import {campaignFor} from './funnel.mjs';
const knownEvents=new Set(['article_request','skill_page_request','skill_download_request','example_download_request','relay_cta_request','relay_download_request']);
let input='';for await(const chunk of process.stdin)input+=chunk;
const counts=new Map();let accepted=0;
for(const line of input.split('\n')){
 let event;try{event=JSON.parse(line);}catch{continue;}
 if(event.schema!=='skill-funnel.v1'&&typeof event.message==='string'&&event.message){try{event=JSON.parse(event.message);}catch{continue;}}
 if(event.schema!=='skill-funnel.v1'||event.skill!=='excel-to-powerpoint'||!/^\d{4}-\d{2}-\d{2}$/.test(event.day)||!knownEvents.has(event.event))continue;
 const campaign=campaignFor(new URL('http://localhost/?campaign='+encodeURIComponent(event.campaign)));
 if(campaign!==event.campaign)continue;
 const key=[event.day,event.skill,campaign,event.event].join(',');counts.set(key,(counts.get(key)||0)+1);accepted++;
}
console.log('day,skill,campaign,event,requests');
for(const [key,count] of [...counts].sort(([a],[b])=>a.localeCompare(b)))console.log(key+','+count);
process.stderr.write(`Accepted ${accepted} website event records; request totals do not establish unique visitors, completed downloads, installs or executions.\n`);
