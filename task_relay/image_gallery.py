"""Presentation of a validated image bundle; no selection or acceptance decisions."""
import base64
import html
import re
from urllib.parse import urlsplit
from orchestrator.image_sources import unpack


def title(reports):
    """Use the supplied document heading, never invent a product identity."""
    for _, content in reports:
        if not isinstance(content,str):raise ValueError('Advisory report must be literal text')
        for line in content.splitlines():
            match=re.fullmatch(r'#{1,2}\s+(.+?)\s*#*',line.strip())
            if match:
                return match[1][:120]
    return 'Image candidates'


def render(raw, reports=()):
    reports=tuple(reports)
    images,credits,manifest=unpack(raw)
    esc=lambda value:html.escape(str(value),quote=True)
    cards=[]
    for name,data in images.items():
        item=credits[name]
        url=item.get('source_url','')
        link='<a href="'+esc(url)+'" rel="noreferrer">Source page</a>' if urlsplit(url).scheme in ('https','http') else 'Source link unavailable'
        cards.append('<article data-candidate="'+esc(item['id'])+'"><img alt="'+esc(item['label'])+'" src="data:'+esc(item['media_type'])+';base64,'+base64.b64encode(data).decode()+'"><div><h2>'+esc(item['label'])+'</h2><p>'+link+'</p><p>Price, dimensions, stock and delivery: unknown unless stated in the accompanying report. Image rights are not verified.</p><details><summary>Image identity</summary><code>'+esc(name)+'<br>'+esc(item['sha256'])+'</code></details></div></article>')
    recommendations=''.join('<details><summary>'+esc(label)+'</summary><pre style="white-space:pre-wrap;font:inherit">'+esc(content)+'</pre></details>' for label,content in reports)
    missing=[s for s in manifest['subjects'] if s['status']!='found']
    gaps=''.join('<li>'+esc(s['label'])+': '+esc(s.get('reason','Image unavailable'))+'</li>' for s in missing)
    return ('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+esc(title(reports))+'''</title><style>body{background:#f4f3ee;color:#26332c;font:16px/1.5 system-ui;margin:0}main{max-width:1200px;margin:auto;padding:32px}h1{font-size:34px}h2{font-size:19px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:22px}article{background:white;border:1px solid #ddd;border-radius:12px;overflow:hidden}article img{width:100%;height:310px;object-fit:contain}article div{padding:20px}a{color:#176347}code{overflow-wrap:anywhere;font-size:11px}details{margin-top:20px}</style><main><h1>'''+esc(title(reports))+'</h1><p>You decide which alternatives fit. AI recommendations are advisory; every acquired candidate remains available.</p><p>'+str(len(images))+' acquired images; '+str(len(missing))+' missing-image records. These are not verified distinct-design counts.</p><div class="grid">'+''.join(cards)+'</div>'+recommendations+'<details><summary>Missing images</summary><ul>'+gaps+'</ul></details></main></html>').encode()


def presentation(raw, reports=()):
    """Three image cards per slide, with full source text retained in slide notes.

    Ranking never controls membership. Notes page within the existing per-slide
    and total slide limits; excess content fails instead of being discarded.
    """
    from orchestrator import pptx_document
    reports=tuple(reports)
    heading=title(reports)
    images,credits,manifest=unpack(raw)
    missing=[s for s in manifest['subjects'] if s['status']!='found']
    # Notes preserve the literal report and unavailable outcomes without filling
    # the visual comparison with pages of prose or model-generated summaries.
    detail='\n\n'.join(label+'\n'+content for label,content in reports)
    if missing:
        detail+='\n\nUnavailable image records\n'+'\n'.join(s['label']+': '+s.get('reason','Image unavailable') for s in missing)
    slides=[]
    def text(value,x,y,w,h,size=20,**extra):
        return dict(type='text',text=value,x=x,y=y,w=w,h=h,font_size=size,color=extra.pop('color','26332C'),**extra)
    def page(elements,notes=''):
        slides.append(dict(background='F4F3EE',notes=notes,elements=elements))
    entries=list(images.items())
    for start in range(0,max(1,len(entries)),3):
        elements=[text(heading,.45,.25,12.4,.65,26,bold=True)]
        notes=[]
        for col,(name,data) in enumerate(entries[start:start+3]):
            item=credits[name];x=.45+col*4.2;url=item.get('source_url','')
            label=' '.join(item['label'].split())
            shown=label if len(label)<=100 else label[:97].rstrip()+'…'
            link={}
            try:pptx_document._hyperlink(url)
            except ValueError:pass
            else:link={'hyperlink':url}
            elements.extend([
                dict(type='shape',shape='rectangle',fill='FFFFFF',x=x,y=1.05,w=4,h=5.65),
                dict(type='image',path=name,x=x+.15,y=1.2,w=3.7,h=3.05,fit='contain'),
                text(shown,x+.17,4.43,3.66,1.05,16,bold=True),
                text('Source page' if link else 'Source link unavailable',x+.17,5.52,3.66,.35,14,color='176347',**link),
                text('Buying details: see advisory notes.\nImage rights unverified. You decide fit.',x+.17,6,3.66,.56,12),
            ])
            notes.append('Candidate: '+item['id']+'\nTitle: '+item['label']+'\nImage member: '+name+'\nSource: '+url+'\nImage SHA-256: '+item['sha256'])
        if not entries:
            elements.append(text('No images acquired. Unavailable sources remain in the notes.',.65,2,12,2,28))
        elements.append(text(f'{len(images)} image entries · {len(missing)} unavailable · Full advice in slide notes · You choose',.5,7,12.3,.3,12))
        page(elements,'\n\n'.join(notes))
    # Fill existing card-slide notes first; add concise notes-index pages only
    # when unusually long input text cannot fit the existing notes allowance.
    i=0
    while detail:
        if i>=len(slides):
            page([text(heading,.45,.25,12.4,.65,26,bold=True),text('Supporting details',.65,2,12,1,32),text('Full advisory text and unavailable sources continue in this slide’s notes.',.65,3.3,11.5,2,24)])
        marker='\n\nAdvisory text / unavailable records (continued in following slide notes if needed)\n'
        remaining=10000-len(slides[i]['notes'])-len(marker)
        if remaining<=0:raise ValueError('Candidate identity exceeds slide notes capacity')
        slides[i]['notes']+=marker+detail[:remaining]
        detail=detail[remaining:];i+=1
    document=dict(version=1,title=heading,font='Arial',size=[13.333333,7.5],slides=slides)
    deck,evidence=pptx_document.create(document,images)
    return deck,dict(evidence=evidence,candidates=len(images),missing_images=len(missing),slides=len(slides),
                     review_status='unreviewed',user_acceptance=False)
