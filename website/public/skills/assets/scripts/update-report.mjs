import fs from "node:fs/promises";
import path from "node:path";
import {createHash} from "node:crypto";
import {pathToFileURL} from "node:url";
import {FileBlob,Workbook,SpreadsheetFile,PresentationFile} from "@oai/artifact-tool";
import {execFileSync} from "node:child_process";
const args=Object.fromEntries(process.argv.slice(2).reduce((a,v,i,arr)=>{if(v.startsWith("--"))a.push([v.slice(2),arr[i+1]]);return a;},[]));
for(const k of ["template","data","mapping","output","tools-dir","python"])if(!args[k])throw Error("Missing --"+k);
const template=path.resolve(args.template),data=path.resolve(args.data),mappingPath=path.resolve(args.mapping),output=path.resolve(args.output),tools=path.resolve(args["tools-dir"]);
if([template,data,mappingPath].includes(output))throw Error("Output must not overwrite an input.");
try{await fs.access(output);throw Error("Output already exists; choose a new output.");}catch(e){if(e.code!=="ENOENT")throw e;}
const cfg=JSON.parse(await fs.readFile(mappingPath,"utf8"));
if(cfg.schema_version!==1||!Array.isArray(cfg.numeric_bindings)||!cfg.numeric_bindings.length)throw Error("Unsupported or empty mapping.");
const hash=async p=>createHash("sha256").update(await fs.readFile(p)).digest("hex");
const inputHashes={template:await hash(template),workbook:await hash(data),mapping:await hash(mappingPath)};
const book=await SpreadsheetFile.importXlsx(await FileBlob.load(data));book.recalculate();
const sheet=book.worksheets.getItem(cfg.sheet);
const raw=cell=>sheet.getRange(cell).values[0][0];
const required=cell=>{const v=raw(cell);if(v===null||v===undefined||v==="")throw Error("Missing required source cell "+cfg.sheet+"!"+cell);return v;};
const number=cell=>{const v=required(cell);if(typeof v!=="number"||!Number.isFinite(v))throw Error("Required numeric source is not finite: "+cell);return v;};
const period=required(cfg.period_cell);
if(typeof period!=="string")throw Error("Period must be explicit text.");
if(required("B4")!==cfg.currency)throw Error("Currency differs from the mapped presentation.");
for(const c of cfg.source_checks??[]){
 const close=(a,b)=>Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(a),Math.abs(b));
 if(c.total&&!close(number(c.total),c.parts.reduce((s,x)=>s+number(x),0)))throw Error("Source reconciliation failed: "+c.total);
 if(c.equal&&!close(number(c.equal[0]),number(c.equal[1])))throw Error("Source values disagree: "+c.equal.join(","));
}
const presentation=await PresentationFile.importPptx(await FileBlob.load(template));
const snap=await presentation.inspect({kind:"slide,textbox,table,chart",include:"id,slide,name,title,text,bbox,rows,cols",maxChars:60000});
const records=snap.ndjson.split("\n").filter(Boolean).map(l=>JSON.parse(l));
const slides=records.filter(r=>r.kind==="slide");
if(slides.length!==cfg.expected_slide_count)throw Error("Template slide count differs.");
const object=(kind,b)=>{
 const found=records.filter(r=>r.kind===kind&&r.slideIndex===b.slide-1&&
  (kind==="textbox"?r.name===b.name:kind==="chart"?r.title?.startsWith(b.title_prefix):true));
 if(kind==="table"){if(!found[b.table])throw Error("Missing table target on slide "+b.slide);return {record:found[b.table],item:presentation.resolve(found[b.table].id)};}
 if(found.length!==1)throw Error("Missing or ambiguous "+kind+" target: "+JSON.stringify(b));
 return {record:found[0],item:presentation.resolve(found[0].id)};
};
const targetKeys=new Set();
const register=(b)=>{const k=JSON.stringify([b.kind,b.slide,b.name??b.title_prefix??b.table,b.row,b.column,b.series,b.point]);if(targetKeys.has(k))throw Error("Duplicate output target "+k);targetKeys.add(k);};
if(!["GBP","USD"].includes(cfg.currency)||cfg.currency_symbol!==({GBP:"£",USD:"$"}[cfg.currency]))throw Error("Unsupported currency symbol");
const format=(v,f)=>f==="money"?cfg.currency_symbol+v.toLocaleString("en-US",{minimumFractionDigits:0,maximumFractionDigits:0}):f==="aov"?cfg.currency_symbol+v.toFixed(2):f==="percent"?(v*100).toFixed(1)+"%":f==="integer"?v.toLocaleString("en-US"):f==="raw"?v:(()=>{throw Error("Unsupported format "+f);})();
for(const b of cfg.numeric_bindings){
 register(b);number(b.cell);
 const o=object(b.kind==="shape"?"textbox":b.kind,b);
 if(b.kind==="table"&&(b.row<0||b.column<0||b.row>=o.record.rows||b.column>=o.record.cols))throw Error("Table target out of bounds.");
 if(b.kind==="chart"&&!cfg.chart_bindings.some(c=>c.slide===b.slide&&c.title_prefix===b.title_prefix&&c.values[b.point]===b.cell))throw Error("Chart numeric binding lacks a complete series mapping.");
}
for(const b of cfg.period_bindings){required(b.cell);object(b.kind==="shape"?"textbox":"chart",b);}
for(const b of cfg.label_bindings??[]){required(b.cell);object("table",b);}
for(const b of cfg.chart_bindings){
 object("chart",b);if(b.categories.length!==b.values.length)throw Error("Chart categories and values differ.");
 b.categories.forEach(required);b.values.forEach(number);
 if(new Set(b.categories.map(required)).size!==b.categories.length)throw Error("Duplicate chart categories need review.");
}
const optional=cfg.optional_commentary,exceptions=[];
if(optional){
 object("textbox",optional);
 if(raw(optional.cell)===null||raw(optional.cell)===undefined||raw(optional.cell)==="")exceptions.push({source:cfg.sheet+"!"+optional.cell,reason:"No approved explanation supplied",disposition:"Human input required; no cause was invented."});
}
if(args["preflight-only"]==="true"){console.log(JSON.stringify({preflight:"pass",numeric_targets:cfg.numeric_bindings.length}));process.exit(0);}
const replaced=[];
for(const b of cfg.numeric_bindings.filter(b=>b.kind!=="chart")){
 const o=object(b.kind==="shape"?"textbox":"table",b),v=format(number(b.cell),b.format);
 if(b.kind==="table")o.item.cells.set(b.row,b.column,String(v));else o.item.text.replace(o.record.text,String(v));
 replaced.push({target:b,source_value:number(b.cell),display_value:v});
}
for(const b of cfg.period_bindings){
 const o=object(b.kind==="shape"?"textbox":"chart",b),v=(b.prefix??"")+required(b.cell)+(b.suffix??"");
 if(b.kind==="shape")o.item.text.replace(o.record.text,v);else o.item.title=v;
}
for(const b of cfg.label_bindings??[])object("table",b).item.cells.set(b.row,b.column,String(required(b.cell)));
for(const b of cfg.chart_bindings){
 const o=object("chart",b).item,s=o.series.getItemAt(b.series);
 s.values=b.values.map(number);s.categories=b.categories.map(required);
}
if(optional){const o=object("textbox",optional);o.item.text.replace(o.record.text,exceptions.length?optional.empty_text:String(raw(optional.cell)));}
const workspace=path.dirname(path.dirname(output));
const build=path.join(workspace,"build","report-"+path.basename(output,".pptx"));
await fs.mkdir(build,{recursive:true});
await fs.writeFile(path.join(build,"before-inspect.ndjson"),snap.ndjson);
const next=await presentation.inspect({kind:"slide,textbox,table,chart",include:"id,slide,name,title,text,bbox,rows,cols",maxChars:60000});
await fs.writeFile(path.join(build,"after-inspect.ndjson"),next.ndjson);
for(let i=0;i<cfg.expected_slide_count;i++){
 const image=await presentation.export({slide:presentation.slides.getItem(i),format:"png",scale:1});
 await fs.writeFile(path.join(build,"slide-"+(i+1)+".png"),new Uint8Array(await image.arrayBuffer()));
}
const {finalizePresentation}=await import(pathToFileURL(path.join(tools,"container_tools/artifact_tool_utils.mjs")).href);
const candidate=path.join(build,"candidate.pptx");
await(await PresentationFile.exportPptx(presentation)).save(candidate);
// Explicit repair for the fixture's local literal snapshots, not live links.
if(cfg.chart_data_policy!=="replace-literal-snapshots")throw Error("An explicit chart data snapshot policy is required.");
const chartBooks=[];
for(let i=0;i<cfg.chart_bindings.length;i++){
 const b=cfg.chart_bindings[i];
 const w=Workbook.create(),s=w.worksheets.add("Chart Data");
 s.getRange("A1:B"+(b.values.length+1)).values=[["Category",object("chart",b).item.series.getItemAt(b.series).name],...b.categories.map((c,j)=>[required(c),number(b.values[j])])];
 const fp=path.join(build,"chart-snapshot-"+(i+1)+".xlsx");
 await(await SpreadsheetFile.exportXlsx(w)).save(fp);
 chartBooks.push({slide:b.slide,title_prefix:b.title_prefix,workbook:fp,categories:b.categories.map(required),values:b.values.map(number)});
}
const repairManifest=path.join(build,"chart-snapshot-manifest.json");
await fs.writeFile(repairManifest,JSON.stringify(chartBooks,null,2));
const packaged=path.join(build,"packaged-"+Date.now()+".pptx");
execFileSync(path.resolve(args.python),[path.join(path.dirname(new URL(import.meta.url).pathname),"attach-chart-workbooks.py"),candidate,packaged,repairManifest],{stdio:"pipe"});
const tableOwners=[...new Set(cfg.numeric_bindings.filter(b=>b.kind==="table").map(b=>b.slide))];
const chartOwners=[...new Set(cfg.chart_bindings.map(b=>b.slide))];
await finalizePresentation({workspaceDir:workspace,candidatePath:packaged,finalPath:output,pythonExecutable:path.resolve(args.python),integrityValidatorPath:path.join(tools,"container_tools/inspect_presentation_package_integrity.py"),layoutValidatorPath:path.join(tools,"container_tools/inspect_presentation_layout_geometry.py"),layoutArgs:["--expected-slide-size-emu","12192000,6858000","--validate-heading-fit",...tableOwners.flatMap(s=>["--require-native-table-slide",String(s)])],explicitTotalSlideCount:cfg.expected_slide_count,requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:chartOwners,materializeLiteralChartWorkbooks:true,fontPolicy:{basis:"reference",families:["Arial"],referencePath:template,referenceSha256:inputHashes.template},verifyArtifactToolImport:true,receiptPath:path.join(build,"native-validation.json")});
if(await hash(template)!==inputHashes.template||await hash(data)!==inputHashes.workbook)throw Error("Input files changed.");
const receipt={period,adapter:"Codex artifact-tool local script",input_sha256:inputHashes,output_sha256:await hash(output),updated_numeric_targets:cfg.numeric_bindings.length,updated_charts:cfg.chart_bindings.length,updated_period_labels:cfg.period_bindings.length,exceptions,replaced,validation:"Native package checks passed. Independent value/layout checks and native application reopen remain separate."};
await fs.writeFile(output+".receipt.json",JSON.stringify(receipt,null,2));
console.log(JSON.stringify({output,period,numeric_targets:cfg.numeric_bindings.length,charts:cfg.chart_bindings.length,period_labels:cfg.period_bindings.length,exceptions:exceptions.length}));
