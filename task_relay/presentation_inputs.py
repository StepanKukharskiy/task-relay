"""Bind slide authors/reviewers to the actual creator's approved image inputs."""
import copy
import json


def restore_selected_images(rt,payload,tasks):
    """Recover exact image dependencies from a selected Relay-created deck.

    This only prepares a new Start proposal. Never infer images by filename or
    extract/relabel arbitrary media from an uploaded presentation.
    """
    from . import production_planning as planning
    from orchestrator.runtime import file_hash
    selected_hashes={s['sha256'] for s in payload['sources']}
    bindings={}
    for source in list(payload['sources']):
        if not source['path'].lower().endswith('.pptx'):continue
        planning.verify_artifact(rt,source)
        originals=rt.db.execute('SELECT * FROM production_artifacts WHERE sha256=? AND attempt IS NOT NULL',(source['sha256'],)).fetchall()
        for artifact in originals:
            if file_hash(artifact['blob'])!=source['sha256']:raise ValueError('Selected presentation origin changed.')
            row=rt.db.execute('SELECT frozen,receipt FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
            frozen=json.loads(row['frozen']);receipt=json.loads(row['receipt'] or '{}')
            if (frozen.get('execution',{}).get('capability')!='pptx.create' or receipt.get('status')!='finished'
                    or receipt.get('operation',{}).get('outcome')!='completed'):continue
            documents=[i for i in frozen['inputs'] if i.get('media_type')=='application/json' and i.get('sha256') in selected_hashes]
            if len(documents)!=1:continue
            original=rt.artifact(documents[0]['artifact'])
            if file_hash(original['blob'])!=documents[0]['sha256']:raise ValueError('Selected slide specification origin changed.')
            from pathlib import Path
            from orchestrator.slide_templates import expand
            document=expand(json.loads(Path(original['blob']).read_text()))
            paths={e['path'] for slide in document['slides'] for e in slide['elements'] if e.get('type')=='image'}
            for item in frozen['inputs']:
                media=item.get('media_type')
                used=(item['path'] in paths if media in ('image/png','image/jpeg') else
                      any(p.startswith(item['path']+'/images/') for p in paths) if media=='application/zip' else False)
                if not used:continue
                previous=bindings.get(item['path'])
                if previous and previous['sha256']!=item['sha256']:raise ValueError('Selected deck image origins are ambiguous.')
                bindings[item['path']]=item
    for creator in tasks:
        if creator.get('execution',{}).get('capability')!='pptx.create':continue
        for path,item in bindings.items():
            if any(i['path']==path for i in creator.get('inputs',[])):continue
            source=planning.source_entry(rt,item['artifact'],'recovery/retained-images/'+item['artifact']+'/'+path,
                'Exact image used by the selected original presentation','Retained image; preserve original content and provenance.')
            planning.verify_artifact(rt,source)
            if source['sha256']!=item['sha256']:raise ValueError('Original presentation image changed.')
            if not any(s['artifact']==source['artifact'] for s in payload['sources']):payload['sources'].append(source)
            creator.setdefault('inputs',[]).append({k:item[k] for k in ('artifact','path','purpose','authority','media_type')})


def identity(item):
    return (item.get('artifact'),item.get('from_task'),item.get('output'))


def bind(tasks):
    by_id={t['id']:t for t in tasks}
    for creator in tasks:
        if creator.get('execution',{}).get('capability')!='pptx.create':continue
        specs=[i for i in creator.get('inputs',[]) if i.get('media_type')=='application/json' and i.get('from_task')]
        for spec in specs:
            producer=by_id[spec['from_task']]
            targets=[producer]+[t for t in tasks if t.get('review_of') in (producer['id'],creator['id'])]
            assets=[i for i in creator.get('inputs',[]) if i.get('media_type') in ('image/png','image/jpeg','application/zip')]
            for target in targets:
                if target.get('execution') or target.get('browser'):continue
                bindings=[]
                for asset in assets:
                    inputs=target.setdefault('inputs',[])
                    source=next((i for i in inputs if identity(i)==identity(asset)),None)
                    if source is None:
                        source=copy.deepcopy(asset)
                        source['path']='creator-inputs/'+creator['id']+'/'+asset['path']
                        if any(i['path']==source['path'] for i in inputs):raise ValueError('Presentation asset binding path collision.')
                        inputs.append(source)
                        if source.get('from_task'):
                            dependency=source['from_task']
                            # A downstream-produced asset cannot be a preparation
                            # source; reject the plan instead of creating a cycle.
                            def depends(task,seen):
                                if task==target['id']:return True
                                if task in seen:return False
                                return any(depends(d,seen|{task}) for d in by_id[task].get('dependencies',[]))
                            if depends(dependency,set()):raise ValueError('Presentation image depends on its own specification; split preparation stages.')
                            if dependency not in target['dependencies']:target['dependencies'].append(dependency)
                    bindings.append({'read_path':source['path'],'slide_path':asset['path'],'media_type':asset['media_type']})
                target['instruction']+=('\nFor new photo collections, prefer the version 2 image_grid layout with style clean_minimal_v1. '
                    'Supply ordered image/label/caption data and per_page 4 or 6; Relay handles geometry and pagination. '
                    'Retain existing slide content and brand decisions when editing. Do not replace a user template without authorization.')
                target['instruction']+='\n\nExact PPTX creator asset bindings (read_path is local; slide_path is the path to write in slide JSON): '+json.dumps(bindings,separators=(',',':'))
                target['instruction']+=('\nFor a ZIP, read manifest.json once and use slide_path + "/" + the exact image member path. '
                    'Do not include angle brackets or substitute local aliases. Validate against the complete bound image list, '
                    'not a list invented from the slide JSON. Report missing subjects honestly; never substitute another species '
                    'or claim an unavailable photo exists. If the user permits unavailable photos to be skipped, omit those image '
                    'elements and photo-only slides, preserve the subject research/text, and record the omissions in the summary. '
                    'Author and reviewers must not block solely on such an authorized omission. Explicit complete-photo '
                    'requirements still apply unless the user relaxes them. Preserve prior content unless the request changes it. '
                    'If a prior image is not among these bindings, report that missing source explicitly rather than silently dropping it.')
