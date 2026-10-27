"""Visual interaction inside a managed Playwright tab; no desktop/OS input."""
import hashlib
import time
import secrets
from orchestrator.browser_visual import MAX_AGE_SECONDS


def state(driver,tab):
    return driver.page(tab).evaluate('''() => ({url:location.href,width:innerWidth,height:innerHeight,
        scroll_x:scrollX,scroll_y:scrollY,dpr:devicePixelRatio,
        scale:visualViewport?.scale||1,offset_x:visualViewport?.offsetLeft||0,offset_y:visualViewport?.offsetTop||0})''')


def remember(session,tab,ident,args,result,viewport):
    capture=result['capture']
    if (capture['width'],capture['height'])!=(viewport['width'],viewport['height']):raise ValueError('Screenshot size differs from CSS viewport')
    detail=dict(capture=secrets.token_hex(16),capture_action_id=ident,observation=args['observation'],tab=tab,path=capture['path'],
                sha256=capture['sha256'],width=capture['width'],height=capture['height'],
                coordinate_space='viewport-css-pixels',expires_after_seconds=MAX_AGE_SECONDS)
    session.visuals[tab]=dict(detail=detail,viewport=viewport,created=time.monotonic())
    result['visual']=detail


def prepare(session,args,operation):
    action=operation.removeprefix('visual_')
    if action not in session.policy.get('visual_actions',[]):raise ValueError('Visual action is not granted')
    if not session.policy['interaction_scope'].strip() or not args['purpose'].strip():raise ValueError('Visual action needs an authorized purpose and scope')
    tab=args['tab'];session.observed(args)
    saved=session.visuals.get(tab)
    if not saved or (args['capture'],args['observation'])!=(saved['detail']['capture'],saved['detail']['observation']):raise ValueError('Capture a fresh screenshot before visual interaction')
    if time.monotonic()-saved['created']>MAX_AGE_SECONDS:raise ValueError('Visual capture expired; take a fresh screenshot')
    v=saved['viewport']
    if state(session.driver,tab)!=v:raise ValueError('Viewport changed; take a fresh screenshot')
    points=[(args['x'],args['y'])]
    if action=='drag':points.append((args['to_x'],args['to_y']))
    if any(not (0<=x<v['width'] and 0<=y<v['height']) for x,y in points):raise ValueError('Visual coordinates must be inside the captured viewport')
    if action=='scroll' and (not (args['delta_x'] or args['delta_y']) or max(abs(args['delta_x']),abs(args['delta_y']))>2000):raise ValueError('Scroll needs a nonzero bounded delta (up to 2000 CSS pixels)')
    if action=='drag' and points[0]==points[1]:raise ValueError('Drag requires distinct points')
    raw=session.files.read_bytes(saved['detail']['path'])
    expected=saved['detail']['sha256']
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Saved visual capture changed')
    # Compare actual pixels as well as DOM: canvas-only changes must invalidate it.
    if hashlib.sha256(session.driver.screenshot(tab)).hexdigest()!=expected:raise ValueError('Page pixels changed; take a fresh screenshot')
    session.observed(args)
    if state(session.driver,tab)!=v:raise ValueError('Viewport changed during visual validation')
    for x,y in points:check_target(session,tab,x,y,action)
    return saved


def check_target(session,tab,x,y,action):
    from orchestrator.browser_action_sets import applicable,check_interaction
    page=session.driver.page(tab)
    handle=page.evaluate_handle('p => document.elementFromPoint(p.x,p.y)',dict(x=x,y=y))
    try:
        if not handle.as_element():raise ValueError('No visible target at visual coordinates')
        ancestors=handle.evaluate('''el => {const out=[];for(let n=el;n;n=n.parentElement){out.push({tag:n.tagName,type:n.getAttribute('type')||'',autocomplete:n.getAttribute('autocomplete')||'',href:n.tagName==='A'?n.href:null,disabled:n.disabled===true||n.getAttribute('aria-disabled')==='true'});}return out;}''')
        for item in ancestors:
            if item['tag'] in ('IFRAME','FRAME','EMBED','OBJECT'):raise ValueError('Visual interaction inside embedded content is not supported')
            if item['type'].lower() in ('password','file') or item['autocomplete'].lower() in ('one-time-code','current-password','new-password'):raise ValueError('Use dedicated file grants; credentials require the user')
            if action!='scroll':
                if item['disabled']:raise ValueError('Visual target is disabled')
                if item['href']:session.url(item['href'])
        # Existing explicit observation-only action grants cannot be bypassed
        # through coordinates. This optional check is not required for other sites.
        if action!='scroll':
            for grant,spec,node in applicable(session.policy,page.url):
                for registered in spec['actions']:
                    matched=handle.evaluate('(el,selector) => !!el.closest(selector)',registered['selector'])
                    if matched:check_interaction(session.policy,dict(action_set=grant['name']), 'click' if action=='click' else action)
    finally:handle.dispose()


def perform(driver,tab,operation,args):
    page=driver.page(tab);action=operation.removeprefix('visual_')
    if action=='click':page.mouse.click(args['x'],args['y'])
    elif action=='scroll':
        page.mouse.move(args['x'],args['y']);page.mouse.wheel(args['delta_x'],args['delta_y'])
    elif action=='drag':
        page.mouse.move(args['x'],args['y'])
        try:
            page.mouse.down();page.mouse.move(args['to_x'],args['to_y'],steps=12)
        finally:page.mouse.up()
    else:raise ValueError('Unsupported visual action')
    # Browser is the only target; no OS cursor, native dialog or keyboard input.
    driver.page(tab)
