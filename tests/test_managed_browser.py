"""Managed browser setup/recovery without real accounts or Chrome processes."""
from contextlib import contextmanager
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from task_relay import credentials, managed_browser as browser, host_managed_chrome as chrome
from task_relay.host import Host
from task_relay.relay_paths import Paths
from task_relay.perplexity_browser import browser_page


class SetupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.paths = Paths(root/'app', root/'data', root/'work', root/'generated')

    def test_status_never_creates_profile_or_launches_browser(self):
        with patch.object(chrome, 'chrome_path', return_value=Path('/fixture/Chrome')), patch.object(chrome, 'ensure') as launch:
            self.assertFalse(browser.status(self.paths)['enabled'])
            self.assertFalse(self.paths.data.exists())
            launch.assert_not_called()

    def test_failed_enable_can_resume_and_disable_retains_profile(self):
        with patch.object(browser.HOST, 'browser_python', return_value='/fixture/python'), \
             patch.object(chrome, 'open_manual', side_effect=ValueError('Chrome is missing')):
            result = browser.configure(True, self.paths)
        self.assertIn('needs attention', result['message'])
        self.assertTrue(browser.preference(self.paths.data)['enabled'])
        marker = self.paths.data/'browser-perplexity/saved-session'
        marker.write_text('fixture')
        with patch.object(browser.HOST, 'browser_python', return_value='/fixture/python'), patch.object(chrome, 'open_manual'):
            browser.open_browser(self.paths)
        self.assertIsNone(browser.preference(self.paths.data)['error'])
        with patch.object(chrome, 'ensure') as launch:
            browser.configure(False, self.paths)
            launch.assert_not_called()
        self.assertEqual(marker.read_text(), 'fixture')
        with self.assertRaisesRegex(ValueError, 'off'):
            with browser_page(marker.parent):pass

    def test_interrupted_enable_retains_intent_and_unknown_version_is_preserved(self):
        with patch.object(browser.HOST, 'browser_python', return_value='/fixture/python'), patch.object(chrome, 'open_manual', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):browser.configure(True, self.paths)
        self.assertTrue(browser.preference(self.paths.data)['enabled'])
        path = self.paths.data/'browser-use.json'
        credentials.save(path, {'version': 2, 'enabled': True})
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'compatible'):browser.configure(False, self.paths)
        self.assertEqual(path.read_bytes(), before)

    def test_worker_uses_enabled_profile_without_legacy_fallback(self):
        credentials.save(self.paths.data/'browser-use.json', {'version': 1, 'enabled': True})
        seen = []
        page = Mock()
        @contextmanager
        def owned(data):
            seen.append(data)
            yield page
        with patch.object(browser, 'page', owned):
            with browser_page(self.paths.data/'browser-perplexity') as driver:
                self.assertIs(driver.page, page)
        self.assertEqual(seen, [self.paths.data])

    def test_general_worker_uses_settings_context_and_shared_job_lock(self):
        from task_relay import general_browser,perplexity_browser
        from tests.test_general_browser import policy
        context=Mock();driver=Mock();events=[]
        @contextmanager
        def lock(data):
            events.append('locked');yield;events.append('unlocked')
        @contextmanager
        def saved(data):
            self.assertEqual(events,['locked']);yield context
        with patch.object(perplexity_browser,'profile_lock',lock),patch.object(browser,'context',saved),patch.object(general_browser,'PlaywrightDriver',return_value=driver) as factory:
            with general_browser.browser(self.paths.data,policy(profile='managed',session_source='settings')) as actual:
                self.assertIs(actual,driver)
            factory.assert_called_once_with(context,policy(profile='managed',session_source='settings'),attached=True)
            driver.detach.assert_called_once()
        self.assertEqual(events,['locked','unlocked'])

    def test_legacy_managed_profile_does_not_switch_to_settings_session(self):
        from task_relay import general_browser
        from tests.test_general_browser import policy
        with patch.object(general_browser,'profile_lock',side_effect=ValueError('Legacy profile')),patch.object(browser,'context') as saved:
            with self.assertRaisesRegex(ValueError,'Legacy profile'):
                with general_browser.browser(self.paths.data,policy(profile='managed')):pass
            saved.assert_not_called()

    def test_general_managed_browser_respects_off_and_manual_signin(self):
        from task_relay.general_browser import browser as general
        from tests.test_general_browser import policy
        for saved,message in [({'version':1,'enabled':False},'off'),
                              ({'version':1,'enabled':True,'manual_sign_in':True},'Complete sign-in')]:
            credentials.save(self.paths.data/'browser-use.json',saved)
            with patch.object(chrome,'ensure') as launch:
                with self.assertRaisesRegex(ValueError,message):
                    with general(self.paths.data,policy(profile='managed',session_source='settings')):pass
                launch.assert_not_called()

    def test_profile_link_is_rejected_without_launch(self):
        with chrome.setup_lock(self.paths.data) as root:
            (root/'chrome-profile').symlink_to(self.paths.workspaces, target_is_directory=True)
            with patch.object(chrome, 'chrome_path', return_value=Path('/fixture/Chrome')), patch.object(chrome.HOST, 'spawn') as spawn:
                with self.assertRaisesRegex(ValueError, 'link'):chrome.ensure(root)
                spawn.assert_not_called()

    def test_live_descriptor_cannot_attach_to_reused_port(self):
        self.paths.data.mkdir()
        (self.paths.data/'DevToolsActivePort').write_text('9223\n/devtools/browser/old')
        with patch.object(chrome, 'resolve_endpoint', return_value='ws://127.0.0.1:9223/devtools/browser/other'):
            self.assertIsNone(chrome.live_socket(self.paths.data))
        with patch.object(chrome, 'resolve_endpoint', return_value='ws://127.0.0.1:9223/devtools/browser/old'):
            self.assertEqual(chrome.live_socket(self.paths.data), 'ws://127.0.0.1:9223/devtools/browser/old')

    def test_reuse_and_interrupted_start_do_not_launch_another_process(self):
        with chrome.setup_lock(self.paths.data) as root:
            credentials.save(root/'chrome-process.json', {'pid': 12345})
            host = Mock(spec=Host)
            host.process_matches.return_value = True
            socket = 'ws://127.0.0.1:9223/devtools/browser/fixture'
            with patch.object(chrome, 'chrome_path', return_value=Path('/fixture/Chrome')), \
                 patch.object(chrome, 'live_socket', side_effect=[None, socket, socket]):
                self.assertEqual(chrome.ensure(root, host=host), socket)
                self.assertEqual(chrome.ensure(root, host=host), socket)
            host.spawn.assert_not_called()

    def test_closed_browser_relaunches_with_same_profile_and_random_loopback_port(self):
        with chrome.setup_lock(self.paths.data) as root:
            host = Mock(spec=Host)
            host.process_matches.return_value = False
            host.spawn.return_value.pid = 23456
            socket = 'ws://127.0.0.1:9223/devtools/browser/new'
            with patch.object(chrome, 'chrome_path', return_value=Path('/fixture/Chrome')), \
                 patch.object(chrome, 'live_socket', side_effect=[None, socket]):
                self.assertEqual(chrome.ensure(root, host=host), socket)
            command = host.spawn.call_args.args[0]
            self.assertIn('--user-data-dir='+str(root/'chrome-profile'), command)
            self.assertIn('--remote-debugging-port=0', command)
            self.assertIn('--remote-debugging-address=127.0.0.1', command)
            self.assertEqual(credentials.private_json(root/'chrome-process.json')['pid'], 23456)

    def test_slow_chrome_start_reuses_one_launch_and_keeps_profile(self):
        clock=[0.0]
        def sleep(seconds):clock[0]+=seconds
        socket='ws://127.0.0.1:9223/devtools/browser/slow'
        with chrome.setup_lock(self.paths.data) as root:
            profile=root/'chrome-profile';profile.mkdir();marker=profile/'saved-session';marker.write_text('retained')
            host=Mock(spec=Host);host.process_matches.return_value=False
            host.spawn.return_value.pid=23456;host.spawn.return_value.poll.return_value=None
            with patch.object(chrome,'chrome_path',return_value=Path('/fixture/Chrome')), \
                 patch.object(chrome,'live_socket',side_effect=lambda _:socket if clock[0]>=10 else None), \
                 patch.object(chrome.time,'monotonic',side_effect=lambda:clock[0]),patch.object(chrome.time,'sleep',sleep):
                self.assertEqual(chrome.ensure(root,host=host),socket)
            host.spawn.assert_called_once();self.assertGreaterEqual(clock[0],10)
            self.assertEqual(host.spawn.call_args.args[0][-1],'chrome://newtab/')
            self.assertEqual(marker.read_text(),'retained')

    def test_startup_remains_bounded_without_relaunch_or_termination(self):
        clock=[0.0]
        with chrome.setup_lock(self.paths.data) as root:
            host=Mock(spec=Host);host.process_matches.return_value=True
            with patch.object(chrome,'chrome_path',return_value=Path('/fixture/Chrome')), \
                 patch.object(chrome,'live_socket',return_value=None),patch.object(chrome.os,'kill') as kill, \
                 patch.object(chrome.time,'monotonic',side_effect=lambda:clock[0]), \
                 patch.object(chrome.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
                with self.assertRaisesRegex(ValueError,'startup limit'):chrome.ensure(root,host=host)
            host.spawn.assert_not_called();kill.assert_not_called()
            self.assertGreaterEqual(clock[0],30);self.assertLess(clock[0],31)

    def test_manual_sign_in_prevents_worker_attachment_until_explicit_done(self):
        with patch.object(browser.HOST, 'browser_python', return_value='/fixture/python'), patch.object(chrome, 'open_manual'):
            browser.configure(True, self.paths)
        self.assertTrue(browser.preference(self.paths.data)['manual_sign_in'])
        with patch.object(chrome, 'ensure') as connect:
            with self.assertRaisesRegex(ValueError, 'Done signing in'):
                with browser.page(self.paths.data):pass
            connect.assert_not_called()
        with patch.object(chrome, 'stop_owned', side_effect=ValueError('Chrome is still open')):
            with self.assertRaises(ValueError):browser.finish_sign_in(self.paths)
        self.assertTrue(browser.preference(self.paths.data)['manual_sign_in'])
        with patch.object(chrome, 'stop_owned'):
            browser.finish_sign_in(self.paths)
        self.assertFalse(browser.preference(self.paths.data)['manual_sign_in'])

    def test_manual_window_has_no_debugging_flags_and_reuses_profile(self):
        with chrome.setup_lock(self.paths.data) as root:
            host = Mock(spec=Host);host.process_matches.return_value = False
            host.spawn.return_value.pid = 23456
            with patch.object(chrome, 'chrome_path', return_value=Path('/fixture/Chrome')), patch.object(chrome, 'stop_owned'):
                chrome.open_manual(root, host)
            command = host.spawn.call_args.args[0]
            self.assertIn('--user-data-dir='+str(root/'chrome-profile'), command)
            self.assertFalse(any('debugging' in arg or 'automation' in arg for arg in command))
            self.assertEqual(command[-1], 'chrome://newtab/')
            self.assertEqual(credentials.private_json(root/'chrome-process.json')['mode'], 'manual')

    def test_unrecognized_browser_process_is_never_terminated(self):
        with chrome.setup_lock(self.paths.data) as root:
            credentials.save(root/'chrome-process.json', {'pid': 23456})
            host = Mock(spec=Host);host.process_matches.return_value = False
            with patch.object(chrome, 'live_socket', return_value='ws://127.0.0.1:9223/devtools/browser/other'), patch.object(chrome.os, 'kill') as kill:
                with self.assertRaisesRegex(ValueError, 'ownership'):chrome.stop_owned(root, host)
                kill.assert_not_called()

    def test_sign_in_cannot_close_browser_in_use_by_a_job(self):
        from task_relay.perplexity_browser import profile_lock
        credentials.save(self.paths.data/'browser-use.json', {'version':1, 'enabled':True})
        with profile_lock(self.paths.data), patch.object(chrome, 'open_manual') as manual:
            with self.assertRaisesRegex(ValueError, 'using this profile'):browser.open_browser(self.paths)
            manual.assert_not_called()
        self.assertNotIn('manual_sign_in', browser.preference(self.paths.data))


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOCAL_BROWSER_FIXTURE') == '1', 'Requires local Chrome fixture')
class ChromeLifecycleTests(unittest.TestCase):
    def test_companion_switch_and_sign_in_button_use_native_setup_actions(self):
        from playwright.sync_api import sync_playwright
        assets = Path(__file__).resolve().parents[1]/'task_relay/assets'
        with sync_playwright() as runtime:
            remote = runtime.chromium.launch(headless=True)
            try:
                page = remote.new_page(viewport={'width': 480, 'height': 700})
                failures = []
                page.on('pageerror', lambda error: failures.append(str(error)))
                page.add_init_script('''
                  window.fixture = {setup:{version:'fixture',providers:{},selected_provider:'later',telegram:{configured:true,paired:true},doctor:{}},
                    service:{healthy:true,loaded:true},conversation:{},browser:{enabled:false,available:true},channels:{},messages:{},decisions:{},folders:[]};
                  window.calls=[];
                  window.__TAURI__={core:{invoke:async (command,{path,value})=>{
                    if(path==='companion-status')return window.fixture;
                    window.calls.push({path,value});
                    if(path==='browser-configure')window.fixture.browser.enabled=value.enabled;
                    if(path==='browser-open')window.fixture.browser.manual_sign_in=true;
                    if(path==='browser-sign-in-done')window.fixture.browser.manual_sign_in=false;
                    return {message:'Saved'};
                  }},event:{listen:async()=>{}},opener:{openUrl:async()=>{}}};
                ''')
                def asset(route):
                    from urllib.parse import urlsplit
                    name = Path(urlsplit(route.request.url).path).name or 'companion.html'
                    if name not in ('companion.html', 'companion.js', 'companion-setup.js', 'companion.css', 'menu-icon.png', 'messages-icon.png'):
                        return route.fulfill(status=404, body='')
                    route.fulfill(path=assets/name)
                page.route('http://127.0.0.1:33222/**', asset)
                page.goto('http://127.0.0.1:33222/')
                page.locator('#settings > summary').click()
                page.locator('#browser-settings > summary').click()
                switch = page.get_by_role('switch', name='Browser use', exact=True)
                switch.click()
                page.wait_for_function("document.getElementById('browser-toggle').getAttribute('aria-checked')==='true'")
                page.get_by_role('button', name='Open browser / sign in', exact=True).click()
                page.wait_for_function('window.calls.length===2')
                self.assertEqual(page.evaluate('window.calls'), [
                    {'path':'browser-configure','value':{'enabled':True}}, {'path':'browser-open','value':{}}])
                self.assertNotIn('Perplexity', page.locator('#browser-settings').inner_text())
                page.screenshot(path='outputs/managed-browser-manual-settings.png', full_page=True)
                page.get_by_role('button', name='Done signing in', exact=True).click()
                page.wait_for_function('window.calls.length===3')
                self.assertEqual(page.evaluate('window.calls[2].path'), 'browser-sign-in-done')
                switch.click()
                page.wait_for_function("document.getElementById('browser-open').disabled")
                page.evaluate('window.fixture.browser.available=false; render(window.fixture)')
                self.assertTrue(switch.is_disabled())
                self.assertTrue(page.get_by_role('link', name='Get Google Chrome').is_visible())
                self.assertEqual(failures, [])
            finally:remote.close()

    def test_launch_reuse_and_restart_retain_private_session(self):
        # Exercise installed Chrome headlessly with a temporary profile and a
        # synthetic cookie. No Perplexity navigation, account or real user tab.
        tmp = tempfile.TemporaryDirectory()
        data = Path(tmp.name).resolve()/'data'
        processes = []
        spawn = chrome.HOST.spawn
        def headless(command, **kwargs):
            process = spawn([*command[:-1], '--headless=new', '--disable-background-networking', 'about:blank'], **kwargs)
            processes.append(process)
            return process
        try:
            credentials.save(data/'browser-use.json', {'version': 1, 'enabled': True})
            with patch.object(chrome.HOST, 'spawn', side_effect=headless):
                with browser.page(data) as page:
                    page.context.add_cookies([{'name': 'fixture', 'value': 'signed-in', 'url': 'http://127.0.0.1', 'expires': time.time()+86400}])
                    first = chrome.descriptor(data/'browser-perplexity/chrome-profile')
                with browser.page(data) as page:
                    self.assertEqual(page.context.cookies('http://127.0.0.1')[0]['value'], 'signed-in')
                self.assertEqual(len(processes), 1)
                paths = Paths(data.parent/'app', data, data.parent/'work', data.parent/'generated')
                browser.open_browser(paths)
                self.assertIsNotNone(processes[0].poll())
                self.assertEqual(len(processes), 2)
                self.assertFalse((data/'browser-perplexity/chrome-profile/DevToolsActivePort').exists())
                with self.assertRaisesRegex(ValueError, 'Done signing in'):
                    with browser.page(data):pass
                browser.finish_sign_in(paths)
                self.assertIsNotNone(processes[1].poll())
                with browser.page(data) as page:
                    self.assertEqual(page.context.cookies('http://127.0.0.1')[0]['value'], 'signed-in')
                    self.assertNotEqual(chrome.descriptor(data/'browser-perplexity/chrome-profile'), first)
                self.assertEqual(len(processes), 3)
        finally:
            for process in processes:
                if process.poll() is None:process.terminate();process.wait(timeout=10)
            tmp.cleanup()


if __name__ == '__main__':unittest.main()
