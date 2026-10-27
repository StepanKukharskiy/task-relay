"""Read-only scoped DOM projection for registered image-render services.

No clicking or retry logic. Unsupported markup produces no usable controls.
"""
import json
from urllib.parse import urlsplit,parse_qs


def observe(page,policy,handles,controls):
    if not any(g==dict(name='xFigura actions',mode='interact') for g in policy.get('custom_actions',[])):return None
    u=urlsplit(page.url);ids=parse_qs(u.query).get('nodeId',[])
    if u.netloc!='app.xfigura.ai' or u.path!='/designer' or len(ids)!=1:return None
    node=ids[0]
    # React Flow's explicit node identity, never a toolbar or a neighbouring node.
    scope=page.locator('.react-flow__node[data-id='+json.dumps(node)+']')
    if scope.count()!=1:return None
    root=scope.element_handle()
    rules={'upload':'input[type="file"]','prompt':'textarea,[contenteditable="true"][role="textbox"]',
           'generate':'button,[role="button"],div.cursor-pointer.pointer-events-auto.bg-brand',
           'download':'a[download],button[aria-label="Download"],button[title="Download"]'}
    found={}
    for role,selector in rules.items():
        matches=[]
        for el in scope.locator(selector).element_handles()[:30]:
            if role!='upload' and not el.is_visible():continue
            if role=='generate' and el.inner_text().strip()!='Generate':continue
            matches.append(el)
        if len(matches)!=1:continue
        el=matches[0]
        from .general_browser import FIELDS
        desc=el.evaluate(FIELDS);value=desc.pop('_value')
        desc.update(render_role=role,render_node=node)
        if role=='prompt':found['prompt']=value or ''
        if role=='generate':desc.update(action_set='xFigura actions',action='generate',action_mode='interact',node_id=node)
        idx=page.evaluate('(a)=>a.handles.findIndex(e=>e===a.el)',dict(handles=handles,el=el))
        if idx<0:
            if len(handles)>=150:continue
            handles.append(el);controls.append(desc)
        else:controls[idx]=desc
    value=root.evaluate('''el=>({busy:el.getAttribute('aria-busy')==='true'||!!el.querySelector('[role="progressbar"],.animate-spin'),
      input_ready:Array.from(el.querySelectorAll('input[type="file"]')).some(e=>e.files?.length===1),
      output:(el.querySelector('a[download]')?.href||''),error:el.querySelector('[role="alert"]')?.textContent||''})''')
    return dict(node=node,prompt=found.get('prompt'),**value)
