"""Lossless tool evidence archive with a bounded model history view."""
import copy
import hashlib
import json
from orchestrator.workers import atomic

INSTRUCTIONS = ('Older browser, file and source results may be replaced by archive references. They are not summaries or proof of product facts. '
                'Use evidence_read with the evidence ID and character offset to retrieve exact saved JSON passages without repeating browser actions. '
                'Save verified product facts incrementally in declared outputs. Only the latest browser observation grants current controls; archived controls can be stale.')
DEFINITION = {'name':'evidence_read','description':'Read exact archived tool evidence from this attempt; no browser action or network request.',
              'parameters':{'type':'object','properties':{'evidence':{'type':'string'},'offset':{'type':'integer','minimum':0}},'required':['evidence','offset']}}

class Archive:
    def __init__(self, control):
        self.folder=control/'context-evidence';self.entries={}

    def save(self, ident, value):
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        self.folder.mkdir(exist_ok=True)
        path=self.folder/(ident+'.json')
        if path.exists() and json.loads(path.read_text())!=value:raise ValueError('Archived browser evidence changed')
        if not path.exists():atomic(path,value)
        # Hash the actual stored serialization, rather than assuming atomic's format.
        self.entries[ident]={'path':path,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return {'evidence':ident,'sha256':self.entries[ident]['sha256'],'bytes':path.stat().st_size,
                **{k:value[k] for k in ('observation','url','tab','error') if k in value},
                'retrieval':'evidence_read; exact JSON retained, facts omitted from this history view'}

    def read(self,args):
        ident=args.get('evidence');offset=args.get('offset')
        if not isinstance(ident,str) or ident not in self.entries:raise ValueError('Unknown evidence in this attempt')
        if type(offset) is not int or offset<0:raise ValueError('Invalid evidence character offset')
        entry=self.entries[ident];raw=entry['path'].read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Archived browser evidence changed')
        text=raw.decode('utf-8')
        if offset>len(text):raise ValueError('Evidence offset exceeds saved text')
        end=min(len(text),offset+8000)
        return {'evidence':ident,'sha256':entry['sha256'],'offset':offset,'text':text[offset:end],
                'next_offset':end if end<len(text) else None}

    def view(self, contents):
        result=copy.deepcopy(contents);refs=[]
        for turn in result:
            for part in turn.get('parts',[]):
                reply=part.get('functionResponse',{})
                if (reply.get('name','').startswith('browser_') or reply.get('name') in ('evidence_read','file_read','sourcing_source_read','evidence_next')) and isinstance(reply.get('response'),dict):refs.append(reply)
        # Keep the latest browser result and latest retrieved excerpt in full.
        keep=set()
        for name in ('browser','retrieval','file_read','sourcing_source_read','evidence_next'):
            indices=[i for i,r in enumerate(refs) if (r['name'].startswith('browser_') if name=='browser' else r['name']==('evidence_read' if name=='retrieval' else name))]
            if indices:keep.add(indices[-1])
        for index,reply in enumerate(refs):
            if index in keep:continue
            value=reply['response']
            if len(json.dumps(value))>4000:reply['response']=self.save('browser-'+str(index),value)
        return result

    def native_view(self, history, provider):
        """Preserve exact native history locally; bound prior read results."""
        result=copy.deepcopy(history)
        results=[r for r in result if r.get('type')=='function_call_output'] if provider=='openai' else [r for r in result if r.get('role')=='tool']
        field='output' if provider=='openai' else 'content'
        for index,reply in enumerate(results[:-1]):
            raw=reply.get(field)
            if not isinstance(raw,str) or len(raw)<=4000:continue
            try:value=json.loads(raw)
            except ValueError:continue
            # Only read-tool evidence; never compact output/revision receipts.
            if not isinstance(value,dict) or not (value.get('parts') and 'remaining' in value or 'text' in value and 'offset' in value):continue
            reply[field]=json.dumps(self.save('native-'+str(index),value),ensure_ascii=False)
        return result
