"""Synthetic DOM only: registered custom actions, denial, stale state and uncertainty."""
import sqlite3
import unittest

from orchestrator.browser_action_sets import validate_grants
from orchestrator.browser_contract import validate
from task_relay.general_browser import PlaywrightDriver, Session
from task_relay.browser_journal import UncertainAction
from tests.test_general_browser import policy


NAME = 'xFigura actions'
URL = 'https://app.xfigura.ai/designer?presistentid=fixture&nodeId=node-1'
CONTROL = '''<div class="flex bg-brand pointer-events-auto cursor-pointer"
onclick="document.querySelector('#effects').textContent=String(Number(document.querySelector('#effects').textContent)+1)">
<div><div><p>Generate</p></div></div></div>'''
HTML = '<body><button aria-label="Generate">Add node</button><span id="effects">0</span>' + CONTROL + '</body>'


class Contracts(unittest.TestCase):
    def test_native_planner_accepts_registered_grants_and_rejects_invented_authority(self):
        from task_relay import planning_contract
        schema=planning_contract.contract({})['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']['browser']
        for mode in ('observe','interact'):
            planning_contract.validate(policy(custom_actions=[dict(name=NAME,mode=mode)]),schema)
        for grant in (dict(name=NAME,mode='automatic'),dict(name='custom xFigure actions',mode='observe'),
                      dict(name=NAME,mode='observe',selector='*')):
            with self.assertRaises(ValueError):
                planning_contract.validate(policy(custom_actions=[grant]),schema)

    def test_explicit_registered_modes_only_and_existing_scope_unchanged(self):
        self.assertNotIn('custom_actions', validate(policy()))
        for bad in (None, 'xFigura actions', [{'name':NAME,'mode':'click'}],
                    [{'name':'custom xFigure actions','mode':'observe'}],
                    [{'name':NAME,'mode':'observe','selector':'*'}],
                    [{'name':NAME,'mode':'observe'}]*2):
            with self.assertRaises(ValueError):validate_grants(bad)
        for mode in ('observe','interact'):
            self.assertEqual(validate(policy(custom_actions=[dict(name=NAME,mode=mode)]))['custom_actions'][0]['mode'],mode)


class DOM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop()

    def setUp(self):
        self.context=self.browser.new_context()
        self.scope=policy(origins=['https://app.xfigura.ai'], custom_actions=[dict(name=NAME,mode='interact')])
        self.driver=PlaywrightDriver(self.context,self.scope)
        # Fulfill every resource locally, including the synthetic HTTPS document.
        # No requests reach xFigura, an account, a model, or any network service.
        self.html=HTML
        self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=self.html))
        self.db=sqlite3.connect(':memory:')
        self.session=Session(self.db,'fixture',self.scope,self.driver)
        self.page=self.session.call('open','browser_open',dict(url=URL))

    def tearDown(self):
        self.context.close();self.db.close()

    def custom(self,page=None):
        return [x for x in (page or self.page)['controls'] if x.get('action_set')==NAME]

    def args(self,page=None):
        p=page or self.page
        return dict(tab=p['tab'],observation=p['observation'],ref=self.custom(p)[0]['ref'],purpose='Click synthetic fixture counter')

    def effects(self):return self.driver.page(self.page['tab']).locator('#effects').inner_text()

    def test_discovery_distinguishes_node_action_and_duplicate_receipt_does_not_reclick(self):
        self.assertEqual(self.effects(),'0')
        self.assertEqual(len(self.custom()),1)
        self.assertEqual(self.custom()[0]['node_id'],'node-1')
        ordinary=[x for x in self.page['controls'] if x['label']=='Generate' and not x.get('action_set')]
        self.assertEqual(len(ordinary),1)
        args=self.args();r=self.session.call('click','browser_click',args)
        self.assertEqual(self.effects(),'1')
        self.assertEqual(self.session.call('click','browser_click',args),r)
        self.assertEqual(self.effects(),'1')

    def test_observe_mode_blocks_click_even_with_nonempty_interaction_scope(self):
        self.scope['custom_actions'][0]['mode']='observe'
        p=self.session.call('read','browser_read',dict(tab=self.page['tab']))
        with self.assertRaisesRegex(ValueError,'observation-only'):
            self.session.call('denied','browser_click',self.args(p))
        self.assertEqual(self.effects(),'0')
        self.assertFalse(self.session.journal.pending('fixture'))

    def test_accessible_custom_control_cannot_bypass_observe_mode(self):
        self.scope['custom_actions'][0]['mode']='observe'
        self.html=HTML.replace('<div class="flex bg-brand','<div role="button" class="flex bg-brand')
        p=self.session.call('accessible','browser_navigate',dict(tab=self.page['tab'],url=URL))
        self.assertEqual(len(self.custom(p)),1)
        self.assertEqual(len([x for x in p['controls'] if x['label']=='Generate']),2)
        with self.assertRaisesRegex(ValueError,'observation-only'):
            self.session.call('denied','browser_click',self.args(p))
        self.assertEqual(self.effects(),'0')

    def test_no_grant_wrong_origin_missing_node_and_ambiguous_controls_not_promoted(self):
        saved=self.scope.pop('custom_actions')
        self.assertFalse(self.custom(self.session.call('none','browser_read',dict(tab=self.page['tab']))))
        self.scope['custom_actions']=saved
        self.html=HTML+CONTROL
        self.page=self.session.call('ambiguous','browser_navigate',dict(tab=self.page['tab'],url=URL))
        self.assertFalse(self.custom())
        self.html=HTML
        self.page=self.session.call('no-node','browser_navigate',dict(tab=self.page['tab'],url='https://app.xfigura.ai/designer'))
        self.assertFalse(self.custom())
        self.scope['origins'].append('https://other.test')
        self.page=self.session.call('wrong-origin','browser_navigate',dict(tab=self.page['tab'],url=URL.replace('app.xfigura.ai','other.test')))
        self.assertFalse(self.custom())

    def test_selected_node_change_invalidates_previous_reference(self):
        args=self.args()
        self.driver.navigate(self.page['tab'],URL.replace('node-1','node-2'))
        with self.assertRaisesRegex(ValueError,'changed'):
            self.session.call('stale','browser_click',args)
        self.assertEqual(self.effects(),'0')

    def test_wrong_operation_and_readonly_scope_block_before_effect(self):
        with self.assertRaisesRegex(ValueError,'only browser_click'):
            self.session.call('press','browser_press',{**self.args(),'key':'Enter'})
        self.scope['interaction_scope']=''
        with self.assertRaisesRegex(ValueError,'reading/navigation only'):
            self.session.call('no-scope','browser_click',self.args())
        self.assertEqual(self.effects(),'0')

    def test_uncertain_custom_click_cannot_be_replayed_under_new_id(self):
        actual=self.driver.act
        def lose(*args):
            actual(*args)
            raise OSError('Synthetic lost response after click')
        self.driver.act=lose
        with self.assertRaises(UncertainAction):self.session.call('lost','browser_click',self.args())
        self.assertEqual(self.effects(),'1')
        self.driver.act=actual
        p=self.session.call('read','browser_read',dict(tab=self.page['tab']))
        with self.assertRaises(UncertainAction):self.session.call('new-id','browser_click',self.args(p))
        self.assertEqual(self.effects(),'1')

class RenderDOM(DOM):
    def test_render_controls_are_scoped_to_selected_node_and_never_toolbar(self):
        import json
        from urllib.parse import urlsplit,parse_qs
        node=parse_qs(urlsplit(URL).query)['nodeId'][0]
        html='<button>Generate</button><div class="react-flow__node" data-id='+json.dumps(node)+'><input type="file"><textarea></textarea><button>Generate</button></div><div class="react-flow__node" data-id="other"><textarea>other</textarea><button>Generate</button><a download href="/old.png">Download</a></div>'
        self.driver.page(self.page['tab']).set_content(html)
        view=self.session.call('render-read','browser_read',dict(tab=self.page['tab']))
        self.assertEqual(view['image_render']['node'],node)
        self.assertFalse(view['image_render']['output'])
        roles=[c for c in view['controls'] if c.get('render_role')]
        self.assertEqual({c['render_role'] for c in roles},{'upload','prompt','generate'})
        self.assertTrue(all(c['render_node']==node for c in roles))
        self.driver.page(self.page['tab']).locator('.react-flow__node').first.evaluate('(el)=>el.remove()')
        view=self.session.call('removed-read','browser_read',dict(tab=self.page['tab']))
        self.assertIsNone(view['image_render'])
