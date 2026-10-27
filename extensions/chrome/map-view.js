import {validateMap,renderMap,svg} from './work-map.js';
const $=id=>document.getElementById(id);
function download(name,content,type){const url=URL.createObjectURL(new Blob([content],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
try{
  const {mapPreview}=await chrome.storage.session.get('mapPreview'),map=await validateMap(mapPreview);
  $('title').textContent=map.title;renderMap($('map'),map);
  $('download-svg').onclick=()=>download('work-map.svg',svg(map),'image/svg+xml');
  $('download-json').onclick=()=>download('work-map.json',JSON.stringify(map,null,2),'application/json');
}catch(error){$('title').textContent='Map unavailable';$('error').textContent='Open a map from Relay’s panel again. '+error.message;$('download-svg').disabled=true;$('download-json').disabled=true;}
