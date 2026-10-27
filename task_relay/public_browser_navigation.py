"""Chromium-native public reads with pre-request checks, including redirects.

Host mechanism only: no model, search provider, publisher rules or user profile.
"""
from urllib.parse import urlsplit
from . import orchestrator_web as web


class Guard:
    def __init__(self, session, main_frame, domains, *, maximum=1000):
        self.session=session;self.main_frame=main_frame;self.domains=domains
        self.maximum=maximum;self.checked={};self.requests=[];self.responses=[];self._errors=[]
        self.cancelled=set();self.settlements=[]
        session.on('Fetch.requestPaused',self.paused)
        session.on('Network.responseReceived',self.response)
        session.on('Network.loadingFailed',self.failed)
        session.send('Network.enable')
        session.send('Fetch.enable',dict(patterns=[dict(urlPattern='*',requestStage='Request')]))

    def paused(self,event):
        request=event['request'];ident=event['requestId']
        url=request['url'];main=event.get('resourceType')=='Document' and event.get('frameId')==self.main_frame
        reason=None
        try:
            if len(self.requests)>=self.maximum:raise ValueError('Public browser request allowance exhausted')
            public=web.public_url(url)
            if request['method'] not in ('GET','HEAD','OPTIONS'):raise ValueError('Public browser permits read methods only')
            from orchestrator.web_sources import allowed
            if main and not allowed(public,self.domains):raise ValueError('Navigation left selected source domains')
            host=urlsplit(public).hostname
            if host not in self.checked:self.checked[host]=web.public_addresses(host)
        except (ValueError,OSError) as exc:reason=str(exc)
        if len(self.requests)<self.maximum+1:
            self.requests.append(dict(request_id=ident,url=url[:4000],method=request['method'],main=main,
                redirected_from=event.get('redirectedRequestId'),outcome='blocked' if reason else 'allowed',reason=reason))
        try:
            self.session.send('Fetch.failRequest' if reason else 'Fetch.continueRequest',
                dict(requestId=ident,**({'errorReason':'BlockedByClient'} if reason else {})))
        except Exception as exc:
            error=str(exc)[:500]
            # A page may cancel an optional request while its Fetch event is
            # being handled. Do not replay it or infer cancellation from the
            # exception alone. The final capture still fails unless Network
            # independently confirms cancellation of this exact network ID.
            if not main and reason is None and event.get('networkId') and 'Invalid InterceptionId' in error:
                if len(self.settlements)<self.maximum:
                    self.settlements.append(dict(request_id=ident,network_id=event['networkId'],error=error))
                    return
            self._errors.append(error)
            # Fail closed if a request cannot be settled; the owning reader
            # checks this and never promotes the resulting page to a capture.
            raise

    def failed(self,event):
        if event.get('canceled') is True and len(self.cancelled)<self.maximum+1:
            self.cancelled.add(event['requestId'])

    @property
    def errors(self):
        return self._errors+[s['error'] for s in self.settlements if s['network_id'] not in self.cancelled]

    def response(self,event):
        if event.get('type')=='Document' and event.get('frameId')==self.main_frame:
            response=event['response']
            self.responses.append(dict(url=response['url'],status=int(response['status'])))

    def evidence(self):
        return dict(version=1,transport='chromium-native',maximum=self.maximum,
                    requests=self.requests,responses=self.responses,errors=self.errors,
                    settlements=[dict(s,outcome='cancelled' if s['network_id'] in self.cancelled else 'unresolved') for s in self.settlements])


def open_page(driver,url,domains):
    """Only owned, isolated Chromium contexts may use this adapter."""
    if driver.attached:raise ValueError('Native public reader cannot adopt an attached user browser')
    context=driver.context
    page=context.new_page();driver.pages['source']=page
    context.unroute('**/*',driver.route)
    # Context routing guards unowned tabs. The CDP guard owns request validation
    # on our tab; continue_ leaves bytes and headers to the browser network stack.
    def owned(route):
        try:
            if route.request.frame.page!=page:return route.abort()
        except Exception:return route.abort()
        return route.continue_()
    context.route('**/*',owned)
    if hasattr(context,'route_web_socket'):context.route_web_socket('**/*',lambda ws:ws.close())
    page.on('popup',lambda popup:popup.close())
    page.on('download',lambda download:download.cancel())
    session=context.new_cdp_session(page)
    frame=session.send('Page.getFrameTree')['frameTree']['frame']['id']
    guard=Guard(session,frame,domains);driver.public_read_guard=guard
    page.goto(url,wait_until='domcontentloaded',timeout=15000)
    # source_browser checks guard.errors after its bounded observation window,
    # allowing already-submitted cancellation receipts to arrive. No new reads.
    return page,guard
