"""Observed browser image references and bounded, public image bundle downloads."""
import hashlib
import io
import json
import time
import zipfile
from urllib.parse import parse_qs, urlsplit
from . import image_sources as sources

SCHEMA = 'relay.browser-image-sources.v1'
DESCRIPTION = '''One application/json manifest exported by browser_image_source from
observed images, not model-authored URLs. Browser scope image_sources=[{path,subjects}]
reserves a JSON output; subjects use {id,label,query}. browser_read lists image refs.
Export an observed original image for each subject using its image ref, never a
Google/Bing thumbnail or screenshot. Missing subjects retain explicit gaps.
images.fetch downloads at most two distinct candidates per subject, public HTTPS
only, without cookies/credentials. Returns the same application/zip photo bundle
as images.collect. Review image identity, suitability and source rights independently.
Unknown author/licence stays unknown; source discovery is not permission to reuse.
The downstream PPTX receives the exact reviewed ZIP and its image paths/credits.
'''


def public_reference(url):
    from task_relay.orchestrator_web import public_url
    url=public_url(url)
    if urlsplit(url).scheme!='https':raise ValueError('Image references require HTTPS')
    if len(url)>4000:raise ValueError('Image reference URL too long')
    return url


def observed_image(image,page_url):
    """Use actual DOM URLs only; decode a search result's explicit original link."""
    link=image.get('href') or ''
    query=parse_qs(urlsplit(link).query)
    original=query.get('imgurl',query.get('mediaurl',[]))
    source=query.get('imgrefurl',[])
    url=public_reference(original[0] if original else image.get('src',''))
    host=urlsplit(url).hostname or ''
    if host.endswith('.gstatic.com') or host=='gstatic.com' or host.endswith('.bing.net'):
        raise ValueError('Search thumbnail is not an original source image; open its preview or source page')
    page_host=urlsplit(page_url).hostname or ''
    search_host=page_host in ('www.google.com','images.google.com','www.bing.com','bing.com','duckduckgo.com')
    source_url=public_reference(source[0] if source else link if search_host else page_url)
    if search_host and (urlsplit(source_url).hostname or '') in ('www.google.com','images.google.com','www.bing.com','bing.com','duckduckgo.com'):
        raise ValueError('Open the result until its original image and publisher link are visible')
    return dict(download_url=url,source_url=source_url,title=(image.get('alt') or 'Observed source image')[:500])


def validate_manifest(value):
    if not isinstance(value,dict) or set(value)!={'schema','job','subjects','candidates'} or value.get('schema')!=SCHEMA or not isinstance(value.get('job'),str) or not 1<=len(value['job'])<=200:
        raise ValueError('Expected an observed browser image-source manifest')
    subjects=value.get('subjects');sources.validate_subjects(subjects)
    candidates=value.get('candidates')
    if not isinstance(candidates,list) or len(candidates)>2*len(subjects):raise ValueError('Image candidate limit exceeded')
    counts={s['id']:0 for s in subjects};seen=set()
    for item in candidates:
        if not isinstance(item,dict) or set(item)!={'subject','download_url','source_url','observed_url','observation','action_id','title'} or item.get('subject') not in counts:raise ValueError('Unknown image subject')
        counts[item['subject']]+=1
        if counts[item['subject']]>2:raise ValueError('At most two image candidates per subject')
        for key in ('download_url','source_url','observed_url'):public_reference(item.get(key,''))
        if not isinstance(item.get('observation'),str) or not item['observation'] or not isinstance(item.get('action_id'),str):raise ValueError('Image needs observed browser provenance')
        if not isinstance(item.get('title'),str) or not 1<=len(item['title'])<=500:raise ValueError('Invalid image title')
        key=(item['subject'],item['download_url'])
        if key in seen:raise ValueError('Duplicate image candidate')
        seen.add(key)
    return value


def fetch_bundle(value,*,fetch=None,seconds=600,max_bytes=sources.MAX_BUNDLE_BYTES,record=None):
    validate_manifest(value)
    deadline=time.monotonic()+seconds;files={};entries=[];total=0
    def journal(event):
        if record:record(event)
    for subject in value['subjects']:
        entry={**subject,'status':'missing','download_failures':[]};entries.append(entry)
        budget={'remaining':8}
        for item in (i for i in value['candidates'] if i['subject']==subject['id']):
            journal(dict(kind='image',status='requested',subject=subject['id'],url=item['download_url']))
            try:
                # Cross-site navigation is not granted here. Only public GETs to
                # the exact observed image/source hosts, including redirect hops.
                hosts={urlsplit(item[k]).hostname for k in ('download_url','source_url')}
                raw,mime,url=(fetch(item['download_url'],sources.MAX_IMAGE_BYTES,deadline) if fetch else
                              sources.download(item['download_url'],sources.MAX_IMAGE_BYTES,deadline,budget,hosts))
                dimensions=sources.image_check(raw,mime)
                if total+len(raw)>min(max_bytes,sources.MAX_BUNDLE_BYTES)-1_000_000:raise ValueError('Image bundle byte limit exceeded')
                path='images/'+subject['id']+('.jpg' if mime=='image/jpeg' else '.png')
                files[path]=raw;total+=len(raw)
                entry.update(item,status='found',path=path,media_type=mime,bytes=len(raw),dimensions=dimensions,
                             sha256=hashlib.sha256(raw).hexdigest(),download_url=url,retrieved_at=time.time(),
                             author='Unknown — check source',license='Unknown — check source',license_url='',
                             match_evidence='Selected from an observed browser page; visual identity and reuse rights require review.')
                journal(dict(kind='image',status='saved',subject=subject['id'],sha256=entry['sha256'],bytes=len(raw)))
                break
            except (ValueError,OSError) as exc:
                failure=dict(url=item['download_url'],reason=str(exc)[:500]);entry['download_failures'].append(failure)
                journal(dict(kind='image',status='failed',subject=subject['id'],**failure))
        if entry['status']=='missing':entry['reason']='; '.join(f['reason'] for f in entry['download_failures']) or 'No original image was selected in the browser for this subject.'
    found=sum(e['status']=='found' for e in entries)
    manifest=dict(version=1,kind='task-relay-sourced-images',provider='browser-sources',created_at=time.time(),
                  subjects=entries,complete=found==len(entries),coverage=dict(found=found,missing=len(entries)-found,total=len(entries)),
                  source_manifest_sha256=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),
                  review='Observed sources are not visual identification or licence verification; independent review required.')
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        for path,raw in files.items():archive.writestr(path,raw)
    if len(buf.getvalue())>max_bytes:raise ValueError('Image bundle output byte limit exceeded')
    return buf.getvalue(),manifest
