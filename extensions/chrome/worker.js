import {chatgptHandoff} from './chatgpt.js';
import {taskRelayCapture} from './extract.js';
const HOST = 'ai.task_relay.capture';
// Declarative panel opening can suppress the action invocation needed for
// activeTab. An explicit toolbar action grants temporary access; it only opens
// the panel, and never captures the page itself. Disable the previous setting
// as well, since Chrome persists it across extension updates.
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: false}).catch(error => console.warn('Task Relay side panel setup failed:', error.message));
chrome.action.onClicked.addListener(tab => {
  if (tab.id == null) return;
  // Call synchronously within the user gesture; no storage/probe await first.
  chrome.sidePanel.open({tabId: tab.id}).catch(error => console.warn('Task Relay panel opening failed:', error.message));
});
// No capture on tab changes or startup. The toolbar grants activeTab; Keep
// injects the extractor into exactly the currently selected document.
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('panel.html') || sender.tab) return false;
  (async () => {
    if(message.type==='open-chatgpt') {
      // Only open/activate the explicit destination. No capture, composer read,
      // draft insertion or Send occurs; activeTab still needs a toolbar click.
      const tab=message.tabId==null?await chrome.tabs.create({url:'https://chatgpt.com/'}):await chrome.tabs.update(message.tabId,{active:true});
      return {tabId:tab.id};
    }
    if (message.type === 'capture') {
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      if (!tab || !tab.url) throw new Error('Click the Task Relay toolbar icon on this webpage, then try Make reusable again.');
      if (!/^https?:\/\//.test(tab.url)) throw new Error('This page cannot be captured. Select a regular webpage such as your ChatGPT conversation, then click the Task Relay toolbar icon there.');
      const results = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: taskRelayCapture, args: [message.selectionOnly===true]});
      const value = results[0]?.result;
      if (!value) throw new Error('The page did not return captured text. Select the text again and retry.');
      const [current] = await chrome.tabs.query({active: true, currentWindow: true});
      if (current?.id !== tab.id || current.url !== (value.url || tab.url)) throw new Error('The page changed during capture. Nothing was retained; capture it again.');
      if (value.captureError) throw new Error(value.captureError);
      return {capture: value};
    }
    if (['chatgpt-inspect', 'chatgpt-insert', 'chatgpt-response', 'chatgpt-recover'].includes(message.type)) {
      if(message.type==='chatgpt-insert'&&message.waitForReady===true){
        if(!await chrome.permissions.contains({origins:['https://chatgpt.com/*']}))throw Object.assign(Error('Enable ChatGPT autofill in Options, or click the Relay toolbar icon in ChatGPT and use Place request.'),{code:'page_access_required'});
        // A bounded wait belongs only to this explicit retained handoff. No
        // navigation listener, startup probe, background capture or Send.
        let ready=false;
        for(let attempt=0;attempt<40;attempt++){
          const destination=await chrome.tabs.get(message.handoff?.tabId);
          const [active]=await chrome.tabs.query({active:true,currentWindow:true});
          if(active?.id!==destination.id)throw Error('Return to the ChatGPT tab and choose Place request in Options. Your request is kept.');
          const onChatGPT=/^https:\/\/chatgpt\.com\//.test(destination.url||'');
          if(destination.url&&destination.url!=='about:blank'&&!onChatGPT)throw Error('The destination changed. Your request is kept in Options; nothing was inserted.');
          if(destination.status==='complete'&&onChatGPT){
            const probe=(await chrome.scripting.executeScript({target:{tabId:destination.id},func:chatgptHandoff,args:['inspect',{}]}))[0]?.result;
            if(probe?.adapter==='chatgpt'){ready=true;break;}
            if(probe?.handoffError&&!/message box was not recognized|message box is unavailable/.test(probe.handoffError))throw Error(probe.handoffError);
          }
          await new Promise(resolve=>setTimeout(resolve,500));
        }
        if(!ready)throw Error('ChatGPT isn’t ready. Sign in or wait, then choose Place request in Options. Your request is kept.');
      }
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      if (!tab?.url) throw Object.assign(Error('Chrome needs access to this tab. Click the Task Relay toolbar icon once, then download here.'),{code:'page_access_required'});
      if (!/^https:\/\/chatgpt\.com\//.test(tab.url)) throw Error('Return to your ChatGPT reply, then download here.');
      const action = message.type.slice('chatgpt-'.length);
      if (!['inspect', 'recover'].includes(action) && tab.id !== message.handoff?.tabId) throw Error('Return to the ChatGPT tab where you prepared this request.');
      // The panel cannot enable attachment matching on an unrelated tab.
      const ticket={...message.handoff,allowAttachmentResponse:action==='response' && message.handoff?.attachmentTabId===tab.id};
      async function readTicket(nextTicket) {
        const [before] = await chrome.tabs.query({active:true,currentWindow:true});
        if(before?.id!==tab.id||before.url!==tab.url)throw Error('The tab changed during the handoff. Return to the original ChatGPT reply, then download again.');
        let results;
        try {results=await chrome.scripting.executeScript({target: {tabId: tab.id}, func: chatgptHandoff, args: [action, nextTicket]});}
        catch(error){if(/Cannot access contents of url|Missing host permission/i.test(error.message||''))throw Object.assign(Error('Chrome needs access to this tab. Click the Task Relay toolbar icon once, then download here.'),{code:'page_access_required'});throw error;}
        const value=results[0]?.result;
        const [current] = await chrome.tabs.query({active: true, currentWindow: true});
        if (current?.id !== tab.id || (value?.url && current.url !== value.url)) throw Error('The tab changed during the handoff. Check ChatGPT before retrying; nothing was sent by Relay.');
        if (!value) throw Error('ChatGPT did not return a handoff result. Check the chat before retrying; Relay did not send anything.');
        return value;
      }
      let value = await readTicket(ticket);
      // React applies Show more after the injected read returns. Wait only for
      // that explicit display change, with one click and a bounded reread. Lost
      // injection replies are never retried; no request is inserted or sent.
      if(['response','recover'].includes(action)&&value.handoffCode==='request_expanded'){
        for(let attempt=0;attempt<10;attempt++){
          await new Promise(resolve=>setTimeout(resolve,100));
          value=await readTicket({...ticket,expansionAttempted:true});
          if(value.handoffCode!=='request_expanding')break;
        }
      }
      if (value.handoffError) throw Object.assign(Error(value.handoffError),{code:value.handoffCode});
      return {...value, tabId: tab.id};
    }
    if (message.type === 'native') {
      if (!await chrome.permissions.contains({permissions: ['nativeMessaging']})) {
        throw new Error('Relay Desktop access is off. You can keep using portable exports, or choose Connect Relay Desktop.');
      }
      const port = chrome.runtime.connectNative(HOST);
      return await new Promise((resolve, reject) => {
        let settled = false;
        port.onMessage.addListener(value => { settled = true; port.disconnect(); value.ok ? resolve(value.result) : reject(new Error(value.error)); });
        port.onDisconnect.addListener(() => { const error = chrome.runtime.lastError; if (!settled) reject(new Error(error?.message || 'Relay bridge disconnected. Save your preview as a download; no action was retried.')); });
        port.postMessage(message.value);
      });
    }
    throw new Error('Unsupported panel action');
  })().then(result => reply({ok: true, result}), error => reply({ok: false, error: error.message,code:error.code}));
  return true;
});
