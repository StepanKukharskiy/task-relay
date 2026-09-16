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
MAX_IMAGE_BYTES = 3_000_000
MAX_BUNDLE_BYTES = 45_000_000
DESCRIPTION = '''parameters={subjects:[{id:"stable-slug",label:"display name",query:"exact subject name"}]}, 1–40 distinct subjects. Optional exclude_titles is an exact list of previously rejected
Commons File: titles; a revision can exclude them without altering prior receipts.
Search Wikimedia Commons once per subject, inspect at most five JPEG/PNG candidates,
and download at most one metadata-matched candidate per subject (no login/key/model).
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


def validate_subjects(subjects):
    if not isinstance(subjects,list) or not 1 <= len(subjects) <= MAX_SUBJECTS:
        raise ValueError('Image search needs 1–40 subjects.')
    seen=set()
    for s in subjects:
        if not isinstance(s,dict) or set(s)-{'exclude_titles'}!={'id','label','query'}:
            raise ValueError('Each subject needs id, label and query.')
        if not isinstance(s['id'],str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',s['id']) or s['id'] in seen:
            raise ValueError('Image subject IDs must be unique safe slugs.')
        seen.add(s['id'])
        excluded=s.get('exclude_titles',[])
        if not isinstance(excluded,list) or len(excluded)>20 or any(not isinstance(t,str) or not t.startswith('File:') or len(t)>500 for t in excluded):
            raise ValueError('Excluded image titles must be bounded Commons File: titles.')
        for key in ('label','query'):
            if not isinstance(s[key],str) or not 1<=len(s[key].strip())<=200 or any(ord(c)<32 for c in s[key]):
                raise ValueError('Image subject text must contain 1–200 printable characters.')
        if any(c in s['query'] for c in '"|{}[]:'):
            raise ValueError('Use a literal subject name, not search operators.')
    return subjects


def download(url, max_bytes, deadline):
    """Pinned public TLS, fixed Wikimedia hosts, no cookies/proxies/auth/retries."""
    from task_relay.orchestrator_web import public_url,public_addresses,PublicHTTPS
    for _ in range(4):
        url=public_url(url);u=urlsplit(url)
        if u.hostname not in ('commons.wikimedia.org','upload.wikimedia.org','thumb.wikimedia.org'):
            raise ValueError('Image-source download is outside Wikimedia hosts.')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('Image-source deadline exceeded.')
        ips=public_addresses(u.hostname)
        conn=PublicHTTPS(u.hostname,ips[0],min(20,remaining))
        try:
            conn.request('GET',u.path+('?' + u.query if u.query else ''),headers={
                'User-Agent':'TaskRelay/0.13 (image sourcing; https://github.com/StepanKukharskiy/task-relay)',
                'Accept':'application/json,image/jpeg,image/png','Accept-Encoding':'identity'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:raise ValueError('Image redirect has no destination.')
                url=urljoin(url,location);continue
            if response.status!=200:raise ValueError('Image source HTTP '+str(response.status))
            mime=response.getheader('Content-Type','').split(';')[0].strip().lower()
            if mime not in ('application/json','image/jpeg','image/png'):
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
        if im.format != {'image/jpeg':'JPEG','image/png':'PNG'}.get(mime) or im.width*im.height>20_000_000 or min(im.size)<100:
            raise ValueError('Invalid or undersized source image.')
        size=im.size;im.verify()
    return list(size)


def candidate(page,subject):
    if page.get('title') in subject.get('exclude_titles',[]):return None
    info=(page.get('imageinfo') or [{}])[0]
    meta=info.get('extmetadata',{})
    field=lambda key:plain(meta.get(key,{}).get('value',''))
    title=plain(page.get('title',''));description=field('ImageDescription')
    needle=normalized(subject['query'])
    if not needle or (' '+needle+' ') not in (' '+normalized(title+' '+description)+' '):return None
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
                match_evidence='Literal query appears in source title/description; subject identity requires review.')


def collect(subjects, *, fetch=None, seconds=600, max_bytes=MAX_BUNDLE_BYTES, record=None):
    validate_subjects(subjects)
    fetch=fetch or download
    deadline=time.monotonic()+seconds;files={};entries=[];total=0
    def journal(value):
        if record:record(value)
    for subject in subjects:
        entry={**subject,'status':'missing'};entries.append(entry)
        query='"'+subject['query']+'" filetype:bitmap'
        url='https://commons.wikimedia.org/w/api.php?'+urlencode(dict(action='query',format='json',
            generator='search',gsrsearch=query,gsrnamespace=6,gsrlimit=5,prop='imageinfo',
            iiprop='url|mime|extmetadata|size',iiurlwidth=1000,iiextmetadatalanguage='en'))
        try:
            journal(dict(subject=subject['id'],kind='search',status='requested',url=url))
            raw,mime,final=fetch(url,1_000_000,deadline)
            if mime!='application/json':raise ValueError('Image search did not return JSON.')
            response=json.loads(raw)
            journal(dict(subject=subject['id'],kind='search',status='responded',url=final,
                         sha256=hashlib.sha256(raw).hexdigest(),response=response))
            if 'error' in response:raise ValueError('Commons search error: '+str(response['error'].get('code','unknown')))
            pages=response.get('query',{}).get('pages',{})
            candidates=[c for p in sorted(pages.values(),key=lambda p:p.get('index',999)) if (c:=candidate(p,subject))]
            if not candidates:raise ValueError('No exact metadata match with supported reuse licence and author.')
            candidates.sort(key=lambda c: normalized(subject['query']) not in normalized(c['title']))
            chosen=candidates[0]
            journal(dict(subject=subject['id'],kind='image',status='requested',url=chosen['download_url']))
            raw,mime,final=fetch(chosen['download_url'],MAX_IMAGE_BYTES,deadline)
            dimensions=image_check(raw,mime)
            if mime!=chosen['media_type']:raise ValueError('Downloaded image differs from source media type.')
            total+=len(raw)
            if total>min(max_bytes,MAX_BUNDLE_BYTES)-1_000_000:raise ValueError('Image bundle byte limit exceeded.')
            path='images/'+subject['id']+('.jpg' if mime=='image/jpeg' else '.png')
            files[path]=raw
            entry.update(chosen,status='found',path=path,sha256=hashlib.sha256(raw).hexdigest(),
                         bytes=len(raw),dimensions=dimensions,download_url=final,retrieved_at=time.time())
            journal(dict(subject=subject['id'],kind='image',status='saved',sha256=entry['sha256'],bytes=len(raw)))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            entry['reason']=str(exc)[:500]
            journal(dict(subject=subject['id'],kind='failure',reason=entry['reason']))
    manifest=dict(version=1,kind='task-relay-sourced-images',provider='wikimedia-commons',
                  created_at=time.time(),subjects=entries,complete=all(e['status']=='found' for e in entries),
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
            if len(entries)>MAX_SUBJECTS+1 or len(set(names))!=len(names) or sum(e.file_size for e in entries)>MAX_BUNDLE_BYTES:
                raise ValueError('Invalid image bundle inventory or byte limit.')
            if any(e.flag_bits&1 or e.is_dir() or (e.external_attr>>16)&0o170000==0o120000 for e in entries):
                raise ValueError('Linked, encrypted or directory bundle entries are unsupported.')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>1_000_000:raise ValueError('Missing or oversized image manifest.')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('version')!=1 or manifest.get('kind')!='task-relay-sourced-images':raise ValueError('Unsupported image bundle.')
            subjects=manifest['subjects'];validate_subjects([{k:s[k] for k in ('id','label','query')} for s in subjects])
            images={};credits={}
            for s in subjects:
                if s['status']=='missing':continue
                if s['status']!='found':raise ValueError('Invalid image subject status.')
                path=s['path']
                if path not in ('images/'+s['id']+'.jpg','images/'+s['id']+'.png') or path in images:
                    raise ValueError('Invalid image bundle path.')
                if archive.getinfo(path).file_size>MAX_IMAGE_BYTES:raise ValueError('Bundled image exceeds byte limit.')
                data=archive.read(path)
                if hashlib.sha256(data).hexdigest()!=s['sha256']:raise ValueError('Image bundle hash mismatch.')
                image_check(data,s['media_type'])
                for field in ('title','author','license','source_url'):
                    if not isinstance(s.get(field),str) or not s[field] or len(s[field])>3000:raise ValueError('Missing image credit metadata.')
                images[path]=data;credits[path]=s
            if set(names)!={'manifest.json',*images}:raise ValueError('Undeclared image bundle files.')
            return images,credits,manifest
    except (KeyError,TypeError,zipfile.BadZipFile,UnicodeError) as exc:
        raise ValueError('Invalid sourced image bundle.') from exc


def presentation_inputs(document,images,bundles):
    """Expand exact bundles and attach provenance to the slides using each image."""
    images=dict(images);document=copy.deepcopy(document);credits={}
    for prefix,raw in bundles.items():
        from .contracts import relative
        relative(prefix)
        found,attributions,manifest=unpack(raw)
        for name,data in found.items():
            path=prefix+'/'+name
            if path in images:raise ValueError('Duplicate presentation image path.')
            images[path]=data;credits[path]=attributions[name]
    for slide in document['slides']:
        used={e.get('path') for e in slide['elements'] if e['type']=='image'}
        notes=[]
        for path in sorted(used&credits.keys()):
            s=credits[path]
            notes.append('Image: '+s['label']+' — '+s['title']+'\nAuthor: '+s['author']+'\nLicence: '+s['license']+' '+s.get('license_url','')+'\nSource: '+s['source_url']+'\nSHA-256: '+s['sha256']+'\nChanges: '+('center-cropped to fill the image box; original source bytes retained.' if any(e.get('path')==path and e.get('fit')=='cover' for e in slide['elements']) else 'none; fitted to slide without cropping.'))
        if notes:slide['notes']=slide.get('notes','')+'\n\nImage sources\n'+'\n\n'.join(notes)
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
    result=dict(outcome='completed',complete=manifest['complete'],found=len(images),subjects=len(subjects),
                output_sha256=hashlib.sha256(raw).hexdigest(),output=str(args.output_dir/'images.zip'))
    (args.output_dir/'receipt.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
