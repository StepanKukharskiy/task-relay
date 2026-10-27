"""Bounded Commons image discovery and immutable, attributed image bundles.

Queries are supplied by the plan; this module has no topic-specific workflow.
Metadata matching produces candidates, not visual or scientific identification.
"""
import copy
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import re
import time
import zipfile
from urllib.parse import urlencode, urlsplit, urljoin

MAX_SUBJECTS = 40
MAX_BUNDLE_SUBJECTS = 400
MAX_SUBJECT_REQUESTS = 8
MAX_IMAGE_BYTES = 3_000_000
MAX_BUNDLE_BYTES = 45_000_000
DESCRIPTION = '''parameters={subjects:[{id:"stable-slug",label:"display name",query:"exact subject name"}]}, 1–40 distinct subjects. Optional exclude_titles is an exact list of previously rejected
Commons File: titles; a revision can exclude them without altering prior receipts.
Search an exact phrase first, then the same literal words in any order if needed.
At most two searches, five candidates per search, two distinct candidate downloads,
and eight HTTP GETs including redirects per subject. Keep at most one image.
Optional identity is an exact name from the request/research that must appear as a
phrase in metadata (use botanical name for plants or place/landmark for scenes).
No transport retry, login, key or model is used. An entirely empty collection fails
with its diagnostic ZIP retained; partial coverage remains available for review.
Queries are literal subject names; resolve scientific names/synonyms from supplied
research, never invent them. The ZIP contains manifest.json and images/<id>.jpg|png.
Manifest records each subject, exact query, found/missing status, source title/page,
author, licence/URL, download URL/time, byte hash and metadata-match evidence.
Missing/ambiguous matches remain explicit gaps; never substitute generated imagery.
A found candidate is not visual or scientific verification: independently review
subject identity and suitability. Use a reviewed bundle as application/zip input to
pptx.create. Image paths are <staged-bundle-path>/images/<id>.jpg|png. Full source
credits are included in slide notes; include short visible captions/credits too.
Preserve exact bundle bytes between steps. Existing decks remain unchanged.
'''


def display_text(text,limit=200):
    """Project source whitespace into bounded display text; evidence stays exact."""
    if not isinstance(text,str):raise ValueError('Image display text must be a string')
    return ' '.join(text.split())[:limit].strip()


def validate_subjects(subjects,maximum=MAX_SUBJECTS,literal_query=True):
    if not isinstance(subjects,list) or not 1 <= len(subjects) <= maximum:
        raise ValueError('Image search needs 1–40 subjects.')
    seen=set()
    for s in subjects:
        if not isinstance(s,dict) or set(s)-{'exclude_titles','identity'}!={'id','label','query'}:
            raise ValueError('Each subject needs id, label and query.')
        if not isinstance(s['id'],str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',s['id']) or s['id'] in seen:
            raise ValueError('Image subject IDs must be unique safe slugs.')
        seen.add(s['id'])
        excluded=s.get('exclude_titles',[])
        if not isinstance(excluded,list) or len(excluded)>20 or any(not isinstance(t,str) or not t.startswith('File:') or len(t)>500 for t in excluded):
            raise ValueError('Excluded image titles must be bounded Commons File: titles.')
        for key in ('label','query',*(['identity'] if 'identity' in s else [])):
            if not isinstance(s[key],str) or not 1<=len(s[key].strip())<=200 or any(ord(c)<32 for c in s[key]):
                raise ValueError('Image subject text must contain 1–200 printable characters.')
        if 'identity' in s and not normalized(s['identity']):
            raise ValueError('Image identity must contain a literal name.')
        if not normalized(s['query']) or literal_query and any(c in s['query'] for c in '"|{}[]:'):
            raise ValueError('Use a literal subject name, not search operators.')
    return subjects


def download(url, max_bytes, deadline, budget=None, allowed_hosts=None, media_types=None):
    """Pinned public TLS, fixed Wikimedia hosts, no cookies/proxies/auth/retries."""
    from task_relay.orchestrator_web import public_url,public_addresses,PublicHTTPS
    for _ in range(4):
        url=public_url(url);u=urlsplit(url)
        if u.hostname not in (allowed_hosts if allowed_hosts is not None else ('commons.wikimedia.org','upload.wikimedia.org','thumb.wikimedia.org')):
            raise ValueError('Image-source download is outside permitted source hosts.')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('Image-source deadline exceeded.')
        if budget is not None:
            if budget['remaining']<=0:raise ValueError('Image subject HTTP request budget exhausted.')
            budget['remaining']-=1
        ips=public_addresses(u.hostname)
        conn=PublicHTTPS(u.hostname,ips[0],min(20,remaining))
        try:
            conn.request('GET',u.path+('?' + u.query if u.query else ''),headers={
                'User-Agent':'TaskRelay/0.13 (image sourcing; https://github.com/StepanKukharskiy/task-relay)',
                'Accept':','.join(media_types or ('application/json','image/jpeg','image/png')),'Accept-Encoding':'identity'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:raise ValueError('Image redirect has no destination.')
                url=urljoin(url,location);continue
            if response.status!=200:raise ValueError('Image source HTTP '+str(response.status))
            mime=response.getheader('Content-Type','').split(';')[0].strip().lower()
            if mime not in (media_types or ('application/json','image/jpeg','image/png')):
                raise ValueError('Image source returned unsupported content.')
            if response.getheader('Content-Encoding','identity') not in ('identity',''):
                raise ValueError('Unexpected compressed image response.')
            if int(response.getheader('Content-Length','0'))>max_bytes:
                raise ValueError('Image response exceeds byte limit.')
            data=bytearray()
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ValueError('Image-source deadline exceeded.')
                if conn.sock:conn.sock.settimeout(min(20,remaining))
                chunk=response.read1(min(65536,max_bytes+1-len(data)))
                if not chunk:break
                data.extend(chunk)
                if len(data)>max_bytes:raise ValueError('Image response exceeds byte limit.')
            return bytes(data),mime,url
        finally:conn.close()
    raise ValueError('Too many image redirects.')


class Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):self.parts.append(data)


def plain(value):
    p=Text();p.feed(str(value));return ' '.join(' '.join(p.parts).split())[:3000]


def normalized(value):
    return ' '.join(re.findall(r'\w+',html.unescape(value).casefold().replace('_',' ')))


def image_check(raw,mime):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        if im.format != {'image/jpeg':'JPEG','image/png':'PNG','image/webp':'WEBP','image/avif':'AVIF'}.get(mime) or im.width*im.height>20_000_000 or min(im.size)<100:
            raise ValueError('Invalid or undersized source image.')
        size=im.size;im.verify()
    return list(size)


def candidate(page,subject,*,keywords=False):
    if page.get('title') in subject.get('exclude_titles',[]):return None
    info=(page.get('imageinfo') or [{}])[0]
    meta=info.get('extmetadata',{})
    field=lambda key:plain(meta.get(key,{}).get('value',''))
    title=plain(page.get('title',''));description=field('ImageDescription')
    needle=normalized(subject['query'])
    haystack=' '+normalized(title+' '+description)+' '
    phrase=bool(needle) and (' '+needle+' ') in haystack
    # Short names (including binomial taxa) retain phrase identity. Longer
    # descriptive queries can vary word order, but never drop a required term.
    words=needle.split()
    if not phrase and not (keywords and len(words)>2 and all(' '+w+' ' in haystack for w in words)):return None
    identity=normalized(subject.get('identity',''))
    if identity and (' '+identity+' ') not in haystack:return None
    # Commons returns the licence for each file, not the website's text licence.
    licence=field('LicenseShortName');licence_url=field('LicenseUrl')
    if not re.fullmatch(r'CC (?:BY(?:-SA)? (?:1\.0|2\.[05]|3\.0|4\.0)|0)',licence) and licence not in ('CC0','Public domain'):
        return None
    if licence not in ('CC0','CC 0','Public domain') and not re.fullmatch(r'https?://creativecommons\.org/licenses/by(?:-sa)?/(?:1\.0|2\.[05]|3\.0|4\.0)(?:/[a-z-]+)?/?',licence_url):return None
    author=field('Artist')
    if not author:return None
    use_original=0 < info.get('size',0)<=MAX_IMAGE_BYTES and 0 < info.get('width',0)*info.get('height',0)<=20_000_000
    url=info.get('url','') if use_original else info.get('thumburl') or info.get('url','')
    if urlsplit(url).hostname not in ('upload.wikimedia.org','thumb.wikimedia.org') or info.get('mime') not in ('image/jpeg','image/png'):return None
    # No SVG/PDF rendering or maps/illustrations knowingly substituted for photos.
    if re.search(r'\b(map|distribution|illustration|drawing|diagram|herbarium|erbario)\b|distmap',normalized(title)):return None
    source=info.get('descriptionurl','')
    if urlsplit(source).hostname!='commons.wikimedia.org':return None
    return dict(title=title,description=description,author=author,license=licence,license_url=licence_url,
                source_url=source,download_url=url,media_type=info['mime'] if use_original else info.get('thumbmime',info['mime']),
                match_evidence=('Literal query phrase' if phrase else 'Every literal query word (order independent)')+
                ' appears in source title/description; subject identity requires review.')


def collect(subjects, *, fetch=None, seconds=600, max_bytes=MAX_BUNDLE_BYTES, record=None):
    validate_subjects(subjects)
    deadline=time.monotonic()+seconds;files={};entries=[];total=0
    def journal(value):
        if record:record(value)
    def collect_one(subject):
        nonlocal total
        budget={'remaining':MAX_SUBJECT_REQUESTS}
        def request(url,limit):
            if fetch is None:return download(url,limit,deadline,budget)
            if budget['remaining']<=0:raise ValueError('Image subject HTTP request budget exhausted.')
            budget['remaining']-=1
            return fetch(url,limit,deadline)
        entry={**subject,'status':'missing','searches':[],'download_failures':[]}
        phrase='"'+subject['query']+'" filetype:bitmap'
        words=' '.join('"'+w+'"' for w in normalized(subject['query']).split())+' filetype:bitmap'
        attempted=set();page_count=0;eligible_count=0
        try:
            for mode,query in [('phrase',phrase),*([('keywords',words)] if words!=phrase else [])]:
                url='https://commons.wikimedia.org/w/api.php?'+urlencode(dict(action='query',format='json',
                    generator='search',gsrsearch=query,gsrnamespace=6,gsrlimit=5,prop='imageinfo',
                    iiprop='url|mime|extmetadata|size',iiurlwidth=1000,iiextmetadatalanguage='en'))
                journal(dict(subject=subject['id'],kind='search',mode=mode,status='requested',url=url))
                raw,mime,final=request(url,1_000_000)
                if mime!='application/json':raise ValueError('Image search did not return JSON.')
                response=json.loads(raw)
                journal(dict(subject=subject['id'],kind='search',mode=mode,status='responded',url=final,
                             sha256=hashlib.sha256(raw).hexdigest(),response=response))
                if 'error' in response:raise ValueError('Commons search error: '+str(response['error'].get('code','unknown')))
                pages=response.get('query',{}).get('pages',{})
                # Bound even a malformed/oversized server inventory.
                pages=sorted(pages.values(),key=lambda p:p.get('index',999))[:5]
                candidates=[c for p in pages if (c:=candidate(p,subject,keywords=mode=='keywords'))]
                page_count+=len(pages);eligible_count+=len(candidates)
                entry['searches'].append(dict(mode=mode,query=query,pages=len(pages),eligible=len(candidates)))
                def relevance(c):
                    title=normalized(c['title']).split();terms=set(normalized(subject['query']).split())
                    # Prefer focused titles over a long caption mentioning the
                    # requested words incidentally. This is ranking, not review.
                    return (normalized(subject['query']) not in ' '.join(title),
                            -sum(t in terms for t in title)/max(1,len(title)))
                candidates.sort(key=relevance)
                for chosen in candidates:
                    if chosen['download_url'] in attempted:continue
                    if len(attempted)>=2:break
                    attempted.add(chosen['download_url'])
                    journal(dict(subject=subject['id'],kind='image',status='requested',url=chosen['download_url']))
                    try:
                        raw,mime,final=request(chosen['download_url'],MAX_IMAGE_BYTES)
                        dimensions=image_check(raw,mime)
                        if mime!=chosen['media_type']:raise ValueError('Downloaded image differs from source media type.')
                    except (ValueError,OSError) as exc:
                        failure=dict(title=chosen['title'],url=chosen['download_url'],reason=str(exc)[:500])
                        entry['download_failures'].append(failure)
                        journal(dict(subject=subject['id'],kind='image',status='failed',**failure))
                        continue
                    if total+len(raw)>min(max_bytes,MAX_BUNDLE_BYTES)-1_000_000:raise ValueError('Image bundle byte limit exceeded.')
                    total+=len(raw)
                    path='images/'+subject['id']+('.jpg' if mime=='image/jpeg' else '.png')
                    files[path]=raw
                    entry.update(chosen,status='found',path=path,sha256=hashlib.sha256(raw).hexdigest(),
                                 bytes=len(raw),dimensions=dimensions,download_url=final,retrieved_at=time.time())
                    journal(dict(subject=subject['id'],kind='image',status='saved',sha256=entry['sha256'],bytes=len(raw)))
                    break
                if entry['status']=='found' or len(attempted)>=2:break
            if entry['status']!='found':
                if not page_count:reason='Commons returned no files for the phrase or same-word search.'
                elif not eligible_count:reason='Search returned files, but none met subject metadata, photo, exclusion, author and reuse-licence requirements.'
                else:reason='Matching candidates could not be downloaded or validated: '+'; '.join(f['reason'] for f in entry['download_failures'])
                raise ValueError(reason)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            entry['reason']=str(exc)[:500]
            journal(dict(subject=subject['id'],kind='failure',reason=entry['reason']))
        entry['http_requests']=MAX_SUBJECT_REQUESTS-budget['remaining']
        return entry
    from .collection_core import collect as collect_subjects
    entries,_=collect_subjects(subjects,[dict(id='commons',version=1,collect=collect_one)],commit=lambda state:journal(dict(kind='collection-checkpoint',status='requested' if state['pending'] else 'checkpointed',state=state)))
    found=sum(e['status']=='found' for e in entries)
    manifest=dict(version=1,kind='task-relay-sourced-images',provider='wikimedia-commons',
                  created_at=time.time(),subjects=entries,complete=found==len(entries),
                  coverage=dict(found=found,missing=len(entries)-found,total=len(entries)),
                  review='Metadata candidates only; visual identity and suitability require independent review.')
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        for name,raw in files.items():archive.writestr(name,raw)
    if len(buf.getvalue())>max_bytes:raise ValueError('Image bundle output byte limit exceeded.')
    return buf.getvalue(),manifest


def unpack(raw):
    """Read declared image bytes in memory, never extract archive paths to disk."""
    if len(raw)>MAX_BUNDLE_BYTES:raise ValueError('Image bundle exceeds byte limit.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();names=[e.filename for e in entries]
            if len(entries)>2*MAX_BUNDLE_SUBJECTS+1 or len(set(names))!=len(names) or sum(e.file_size for e in entries)>MAX_BUNDLE_BYTES:
                raise ValueError('Invalid image bundle inventory or byte limit.')
            if any(e.flag_bits&1 or e.is_dir() or (e.external_attr>>16)&0o170000==0o120000 for e in entries):
                raise ValueError('Linked, encrypted or directory bundle entries are unsupported.')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>1_000_000:raise ValueError('Missing or oversized image manifest.')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('version')!=1 or manifest.get('kind')!='task-relay-sourced-images':raise ValueError('Unsupported image bundle.')
            subjects=manifest['subjects']
            if subjects==[]:
                if not (manifest.get('empty_catalog') is True and manifest.get('coverage')==dict(found=0,missing=0,total=0)
                        and re.fullmatch('[a-f0-9]{64}',manifest.get('source_catalog_sha256',''))):
                    raise ValueError('Empty photo bundle needs explicit zero-option catalog provenance')
            else:validate_subjects([{k:s[k] for k in ('id','label','query')} for s in subjects],maximum=MAX_BUNDLE_SUBJECTS,literal_query=False)
            revision=manifest.get('evidence_revision',{})
            retained=revision.get('version')==2
            if retained and (set(revision)!={'version','base_sha256','rejections'}
                    or not re.fullmatch('[a-f0-9]{64}',revision.get('base_sha256',''))
                    or not isinstance(revision.get('rejections'),dict)):
                raise ValueError('Invalid retained evidence revision')
            history=manifest.get('retained_evidence',[])
            if not isinstance(history,list) or len(history)>MAX_BUNDLE_SUBJECTS:raise ValueError('Invalid retained evidence history')
            checks=[(s,'',False) for s in subjects]
            for entry in history:
                if (not isinstance(entry,dict) or set(entry)!={'bundle_sha256','subject'}
                        or not re.fullmatch('[a-f0-9]{64}',entry.get('bundle_sha256',''))):
                    raise ValueError('Invalid retained evidence origin')
                prior=entry['subject']
                if not isinstance(prior,dict) or prior.get('status')!='found':raise ValueError('Invalid retained evidence subject')
                validate_subjects([{k:prior[k] for k in ('id','label','query')}],literal_query=False)
                checks.append((prior,'history/'+entry['bundle_sha256']+'/',True))
            images={};credits={};originals=set();quarantined=set()
            for s,prefix,historical in checks:
                rejected=s['status']=='missing' and retained and 'rejected_evidence' in s
                if s['status']=='missing' and not rejected:continue
                if rejected:
                    prior=s['rejected_evidence']
                    if (not isinstance(prior,dict) or prior.get('status')!='found'
                            or any(prior.get(k)!=s.get(k) for k in ('id','label','query'))
                            or revision['rejections'].get(s['id'])!=s.get('reason')):
                        raise ValueError('Rejected evidence identity or reason changed')
                    s=prior
                if s['status']!='found':raise ValueError('Invalid image subject status.')
                path=prefix+s['path']
                if s['path'] not in ('images/'+s['id']+'.jpg','images/'+s['id']+'.png') or path in images or path in quarantined:
                    raise ValueError('Invalid image bundle path.')
                if archive.getinfo(path).file_size>MAX_IMAGE_BYTES:raise ValueError('Bundled image exceeds byte limit.')
                data=archive.read(path)
                if hashlib.sha256(data).hexdigest()!=s['sha256']:raise ValueError('Image bundle hash mismatch.')
                image_check(data,s['media_type'])
                original=s.get('source_original')
                if original is not None:
                    if not isinstance(original,dict) or set(original)!={'path','media_type','bytes','sha256','transformation'}:
                        raise ValueError('Invalid source-original metadata.')
                    original_path=prefix+original['path']
                    source_format={'image/webp':'webp','image/avif':'avif'}.get(original['media_type'])
                    if not source_format or original['path']!='originals/'+s['id']+'.'+source_format or original_path in originals or original['transformation'] not in ('lossless-'+source_format+'-to-png','bounded-preview-v1-'+source_format+'-to-png') or s['media_type']!='image/png':
                        raise ValueError('Invalid source-original path or conversion.')
                    if archive.getinfo(original_path).file_size>MAX_IMAGE_BYTES:raise ValueError('Source original exceeds byte limit.')
                    source=archive.read(original_path)
                    if len(source)!=original['bytes'] or hashlib.sha256(source).hexdigest()!=original['sha256']:
                        raise ValueError('Source-original hash mismatch.')
                    if original['transformation'].startswith('bounded-preview-v1-'):
                        from .image_representation import verify_preview
                        image_check(source,original['media_type'])
                        verify_preview(source,data,original['media_type'],original['transformation'],MAX_IMAGE_BYTES)
                    else:
                        if image_check(source,original['media_type'])!=image_check(data,'image/png'):
                            raise ValueError('Source-original dimensions changed.')
                        from PIL import Image
                        with Image.open(io.BytesIO(source)) as before, Image.open(io.BytesIO(data)) as after:
                            if getattr(before,'n_frames',1)!=1 or before.convert('RGBA').tobytes()!=after.convert('RGBA').tobytes():
                                raise ValueError('Converted photo pixels differ from source original.')
                    originals.add(original_path)
                if rejected or historical:quarantined.add(path)
                else:images[path]=data;credits[path]=s
            if retained and set(revision['rejections'])!={s['id'] for s in subjects if s['status']=='missing' and 'rejected_evidence' in s}:
                raise ValueError('Retained evidence subjects differ from rejection decisions')
            if set(names)!={'manifest.json',*images,*originals,*quarantined}:raise ValueError('Undeclared image bundle files.')
            return images,credits,manifest
    except (KeyError,TypeError,zipfile.BadZipFile,UnicodeError) as exc:
        raise ValueError('Invalid sourced image bundle.') from exc


def revision_contract(frozen, raw):
    """Only an explicitly partial-coverage read can quarantine saved evidence."""
    if frozen.get('execution',{}).get('parameters',{}).get('count_policy')!='target':return None
    _,_,manifest=unpack(raw)
    return dict(version=2,base_sha256=hashlib.sha256(raw).hexdigest(),
                subjects=[s['id'] for s in manifest['subjects'] if s['status']=='found'])


def revise_bundle(raw, rejections, *, version=2):
    """Create a local evidence projection; never replace or relabel source pixels.

    Both the immutable base and new archive retain all bytes and receipts.
    Consumers receive only usable photographs. Version 1 is retained solely
    to validate historical projections before a bounded format repair.
    """
    import copy
    if version not in (1,2):raise ValueError('Unknown evidence projection version')
    _,_,manifest=unpack(raw)
    found={s['id']:s for s in manifest['subjects'] if s['status']=='found'}
    if (not isinstance(rejections,dict) or not rejections or set(rejections)-set(found)
            or any(not isinstance(r,str) or not r.strip() or len(r)>2000 for r in rejections.values())):
        raise ValueError('Evidence revision needs exact found subject IDs and review-backed reasons')
    result=copy.deepcopy(manifest);removed=set()
    for entry in result['subjects']:
        if entry['id'] not in rejections:continue
        previous=copy.deepcopy(entry);removed.add(entry['path'])
        if entry.get('source_original'):removed.add(entry['source_original']['path'])
        entry.clear();entry.update({k:previous[k] for k in ('id','label','query')})
        entry.update(status='missing',reason=rejections[entry['id']],rejected_evidence=previous)
    count=sum(s['status']=='found' for s in result['subjects'])
    result.update(complete=count==len(result['subjects']),
        coverage=dict(found=count,missing=len(result['subjects'])-count,total=len(result['subjects'])),
        evidence_revision=dict(version=version,base_sha256=hashlib.sha256(raw).hexdigest(),rejections=rejections))
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as before,zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as after:
        after.writestr('manifest.json',json.dumps(result,ensure_ascii=False,indent=2).encode())
        for name in before.namelist():
            if name!='manifest.json' and (version==2 or name not in removed):after.writestr(name,before.read(name))
    unpack(output.getvalue())
    return output.getvalue()


def validate_revision(before, after, contract):
    """Validate the entire projection, not merely a model's integrity claim."""
    _,_,result=unpack(after)
    if contract.get('version') not in (1,2) or contract.get('base_sha256')!=hashlib.sha256(before).hexdigest():
        raise ValueError('Evidence revision base changed')
    marker=result.get('evidence_revision',{})
    if 'locked_rejections' in contract and marker.get('rejections')!=contract['locked_rejections']:
        raise ValueError('Evidence format repair changed rejection decisions')
    expected=revise_bundle(before,marker.get('rejections'),version=contract['version'])
    with zipfile.ZipFile(io.BytesIO(expected)) as wanted,zipfile.ZipFile(io.BytesIO(after)) as actual:
        if set(wanted.namelist())!=set(actual.namelist()):raise ValueError('Evidence revision changed archive members')
        for name in wanted.namelist():
            a,b=wanted.read(name),actual.read(name)
            different=json.loads(a)!=json.loads(b) if name=='manifest.json' else a!=b
            if different:
                raise ValueError('Evidence revision changed retained evidence or provenance')


def repair_revision(before, after, contract):
    """Admit only an exact historical projection; restore bytes, not usability."""
    if contract.get('version')!=1:return None
    validate_revision(before,after,contract)
    _,_,manifest=unpack(after)
    rejections=manifest['evidence_revision']['rejections']
    return dict(**{**contract,'version':2},locked_rejections=rejections)


def subject_base_bundle(subjects, catalog_sha256):
    """Code-owned subject inventory for independent discovery batches; no image evidence."""
    if any(set(s)!={'id','label','query'} for s in subjects):
        raise ValueError('A subject base contains only IDs, labels and literal queries.')
    validate_subjects(subjects)
    if not isinstance(catalog_sha256,str) or not re.fullmatch('[0-9a-f]{64}',catalog_sha256):
        raise ValueError('Subject inventory needs its exact source catalog hash.')
    manifest=dict(version=1,kind='task-relay-sourced-images',provider='code-subject-inventory',
                  subjects=[{**copy.deepcopy(s),'status':'missing',
                             'reason':'Subject declared from catalog; image discovery pending.'} for s in subjects],
                  source_catalog_sha256=catalog_sha256,complete=False,
                  coverage=dict(found=0,missing=len(subjects),total=len(subjects)),
                  review='This inventory contains no photos, observations or licence verification.')
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_STORED) as archive:
        archive.writestr(zipfile.ZipInfo('manifest.json',(1980,1,1,0,0,0)),
                         json.dumps(manifest,ensure_ascii=False,indent=2))
    return result.getvalue()


def merge_bundles(bundles, *, max_bytes=MAX_BUNDLE_BYTES):
    """First ZIP defines subjects; successors fill gaps without replacing found bytes."""
    if not isinstance(bundles,list) or not 2<=len(bundles)<=20:
        raise ValueError('Photo merge requires a base and bounded recovery bundles.')
    if any(not isinstance(raw,bytes) for raw in bundles) or sum(map(len,bundles))>MAX_BUNDLE_BYTES:
        raise ValueError('Photo merge input byte limit exceeded.')
    parsed=[unpack(raw) for raw in bundles]
    base=copy.deepcopy(parsed[0][2]);subjects={s['id']:s for s in base['subjects']}
    files={};provenance=[];missing_receipts=[];history=[];history_keys=set()
    for index,(raw,(images,credits,manifest)) in enumerate(zip(bundles,parsed)):
        digest=hashlib.sha256(raw).hexdigest();provenance.append(digest)
        missing=[copy.deepcopy(s) for s in manifest['subjects'] if s['status']=='missing']
        if missing:missing_receipts.append(dict(bundle_sha256=digest,subjects=missing))
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            retained=list(manifest.get('retained_evidence',[]))
            retained.extend(dict(bundle_sha256=digest,subject=s['rejected_evidence']) for s in manifest['subjects']
                            if s['status']=='missing' and manifest.get('evidence_revision',{}).get('version')==2 and 'rejected_evidence' in s)
            for entry in retained:
                prior=entry['subject'];key=(entry['bundle_sha256'],prior['id'])
                if key in history_keys:continue
                history_keys.add(key);history.append(copy.deepcopy(entry))
                paths=[prior['path']]+([prior['source_original']['path']] if prior.get('source_original') else [])
                prefix='history/'+entry['bundle_sha256']+'/'
                for path in paths:
                    source=prefix+path if entry in manifest.get('retained_evidence',[]) else path
                    files[prefix+path]=archive.read(source)
            for subject in manifest['subjects']:

                ident=subject['id']
                if ident not in subjects:raise ValueError('Recovery introduced an undeclared photo subject.')
                current=subjects[ident]
                if any(subject[k]!=current[k] for k in ('label','query')):
                    raise ValueError('Recovery changed photo subject identity.')
                if subject['status']!='found':
                    if current['status']=='missing':subjects[ident]=copy.deepcopy(subject)
                    continue
                if index and current['status']=='found':
                    if current['sha256']!=subject['sha256']:
                        raise ValueError('Recovery cannot replace an already found photo.')
                    continue  # Preserve its original attribution/observation as well as pixels.
                subjects[ident]=copy.deepcopy(subject)
                files[subject['path']]=images[subject['path']]
                if subject.get('source_original'):
                    original=subject['source_original'];files[original['path']]=archive.read(original['path'])
    base.pop('evidence_revision',None)
    base['retained_evidence']=history
    base['subjects']=list(subjects.values());found=sum(s['status']=='found' for s in base['subjects'])
    base.update(provider='reviewed-bundle-merge',created_at=time.time(),complete=found==len(subjects),
                coverage=dict(found=found,missing=len(subjects)-found,total=len(subjects)),
                source_bundle_sha256=provenance,source_missing_subjects=missing_receipts,
                review='Merged recorded source bundles. Image identity, suitability and reuse rights require independent review; missing-source receipts are retained.')
    # A merge is not a newly exported browser manifest; originals retain their receipts.
    for key in ('source_manifest_sha256','source_manifest_hash_basis','source_manifest_canonical_sha256'):
        base.pop(key,None)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json',json.dumps(base,ensure_ascii=False,indent=2))
        for name,data in files.items():archive.writestr(name,data)
    result=buf.getvalue()
    if len(result)>min(max_bytes,MAX_BUNDLE_BYTES):raise ValueError('Merged photo bundle exceeds byte limit.')
    unpack(result)
    return result,base


def presentation_inputs(document,images,bundles):
    """Expand exact bundles without changing authored slide notes."""
    images=dict(images);document=copy.deepcopy(document);credits={}
    for prefix,raw in bundles.items():
        from .contracts import relative
        relative(prefix)
        found,attributions,manifest=unpack(raw)
        for name,data in found.items():
            path=prefix+'/'+name
            if path in images:raise ValueError('Duplicate presentation image path.')
            images[path]=data;credits[path]=attributions[name]
    return document,images


def main(argv=None):
    import argparse
    import os
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('subjects',type=Path,help='JSON array of exact subject requests')
    parser.add_argument('--output-dir',required=True,type=Path,help='New directory; never replaces existing outputs')
    args=parser.parse_args(argv)
    subjects=validate_subjects(json.loads(args.subjects.read_text()))
    args.output_dir.mkdir(parents=True,exist_ok=False)
    (args.output_dir/'request.json').write_text(json.dumps(dict(capability='images.collect',version=1,
        parameters={'subjects':subjects},requested_at=time.time()),ensure_ascii=False,indent=2))
    def record(value):
        with (args.output_dir/'requests.jsonl').open('a') as stream:
            stream.write(json.dumps(value,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    raw,manifest=collect(subjects,record=record)
    (args.output_dir/'images.zip').write_bytes(raw)
    (args.output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    # The directory is newly reserved and member paths were verified in memory.
    # These are inspectable source assets, identical to the bytes in the bundle.
    images,_,_=unpack(raw)
    for path,data in images.items():
        target=args.output_dir/path;target.parent.mkdir(exist_ok=True)
        with target.open('xb') as stream:stream.write(data)
    result=dict(outcome='completed' if images else 'failed',complete=manifest['complete'],found=len(images),subjects=len(subjects),
                output_sha256=hashlib.sha256(raw).hexdigest(),output=str(args.output_dir/'images.zip'))
    (args.output_dir/'receipt.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
