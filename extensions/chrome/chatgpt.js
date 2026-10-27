// Serialized into the authorized tab by chrome.scripting. Keep this function
// self-contained: no network, background listeners, sending or extension APIs.
export function chatgptHandoff(action, payload = {}) {
  // Chrome may resolve script injection without a result when the injected
  // function throws. Return expected recovery errors explicitly across that
  // boundary, so the worker does not mistake them for navigation.
  try {
  const here = new URL(location.href);
  if (here.protocol !== 'https:' || here.hostname !== 'chatgpt.com' ||
      !(here.pathname === '/' || /^\/c\/[^/]+\/?$/.test(here.pathname))) {
    throw Error('Open a ChatGPT conversation and click the Relay toolbar icon there. Other pages use the copy/import route.');
  }
  function visible(el) {
    if (!el || el.closest('[hidden],[aria-hidden="true"],[inert]')) return false;
    for (let n = el; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse' || Number(s.opacity) === 0) return false;
    }
    return el.getClientRects().length > 0 || (getComputedStyle(el).display === 'contents' && [...el.querySelectorAll('*')].some(visible));
  }
  const normalize = text => String(text).replace(/\s+/g, ' ').trim();
  const text = el => el.innerText ?? el.textContent ?? '';
  function inlineText(el) {
    // innerText inserts layout line breaks around inline links. Preserve actual
    // text and explicit BRs so a URL in quoted JSON still matches the request.
    // ChatGPT marks visually rendered links inert/aria-hidden in collapsed
    // user turns. Those attributes disable interaction, not the displayed URL.
    if (el.hidden || ['BUTTON','SCRIPT','STYLE'].includes(el.tagName) || el.getAttribute('data-markdown-copy') === 'exclude') return '';
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return '';
    if (!el.childNodes?.length) return el.textContent ?? text(el);
    return [...el.childNodes].map(node => node.nodeType === 3 ? node.textContent : node.nodeName === 'BR' ? '\n' : node.nodeType === 1 ? inlineText(node) : '').join('');
  }
  function messages() {
    const legacy = [...document.querySelectorAll('[data-message-author-role]')].filter(visible);
    if (legacy.length) return legacy.map(el => ({el, role: el.getAttribute('data-message-author-role')}));
    // The current Work layout exposes role headings inside virtualized turns,
    // rather than data-message-author-role. Keep role/header boundaries explicit.
    return [...document.querySelectorAll('[data-turn-key] h4.sr-only')].map(heading => {
      const role = heading.getAttribute('data-conversation-role') === 'assistant' ? 'assistant' : heading.textContent.trim() === 'You said:' ? 'user' : null;
      return {el: heading.parentElement, role, heading};
    }).filter(row => row.role && visible(row.el));
  }
  function messageText(row) {
    if(row.role==='user'){
      const paragraphs=[...row.el.querySelectorAll('p')].filter(el=>visible(el)&&!el.closest('pre,code,button'));
      const header=paragraphs.map(inlineText).join('\n\n');
      if(/TASK_RELAY_BODY_V[23]/.test(header)){
        const code=[...row.el.querySelectorAll('pre code,code[class*="CodeContent-"]')].filter(visible);
        const fence=header.includes('TASK_RELAY_BODY_V3')?'```':'~~~~';
        if(code.length===1)return header+'\n'+fence+'text\n'+code[0].textContent.replace(/\n$/,'')+'\n'+fence;
      }
    }
    const paragraphs = row.heading && row.role === 'user' ? [...row.el.querySelectorAll('p')].filter(el => visible(el) && !el.closest('button')) : [];
    const content = paragraphs.length ? paragraphs.map(inlineText).join('\n\n') : text(row.el);
    if (!row.heading) return content;
    const label = row.heading.textContent.trim();
    return content.trimStart().startsWith(label) ? content.trimStart().slice(label.length).trimStart() : content;
  }
  function contextText(request){
    if(/\nTASK_RELAY_BODY_V[23]\n/.test(request)){const fence=request.includes('\nTASK_RELAY_BODY_V3\n')?'```':'~~~~',opening=fence+'text\n',start=request.indexOf(opening);if(start<0||!request.endsWith('\n'+fence))throw Error('The literal Relay request is incomplete');request=request.slice(start+opening.length,-fence.length-1);}
    return request.slice(request.lastIndexOf('\n\n')+2);
  }
  function expandRequest(row) {
    const controls = [...row.el.querySelectorAll('button')].filter(el => visible(el) && text(el).trim() === 'Show more' && !el.disabled && el.getAttribute('aria-disabled') !== 'true');
    if (controls.length !== 1) return null;
    if (payload.expansionAttempted === true) return {url:here.href,handoffError:'ChatGPT is still expanding the request. Try Download again.',handoffCode:'request_expanding'};
    controls[0].click();
    return {url:here.href,handoffError:'Expanding the submitted Relay request.',handoffCode:'request_expanded'};
  }
  function composer() {
    const inputs = [...document.querySelectorAll('#prompt-textarea,[data-composer-markdown][contenteditable="true"][role="textbox"]')].filter(visible);
    if (inputs.length !== 1 || !(inputs[0].tagName === 'TEXTAREA' || inputs[0].getAttribute('contenteditable') === 'true')) {
      throw Error('ChatGPT’s message box was not recognized. Use Copy request instead.');
    }
    if (inputs[0].disabled || inputs[0].getAttribute('aria-disabled') === 'true') throw Error('ChatGPT’s message box is unavailable. Try again when it is ready.');
    return inputs[0];
  }
  function value(el) { const paragraphs=[...el.querySelectorAll('p')];return el.tagName==='TEXTAREA'?el.value:paragraphs.length?paragraphs.map(inlineText).join('\n\n'):inlineText(el); }
  const streaming = () => [...document.querySelectorAll('[data-testid="stop-button"],[aria-label="Stop generating"],[data-is-streaming="true"]')].some(visible);
  if (action === 'inspect') {
    const el=composer(),paragraphs=[...el.querySelectorAll('p')];
    const draft=el.tagName==='TEXTAREA'?el.value:paragraphs.length?paragraphs.map(inlineText).join('\n\n'):inlineText(el);
    const requestId=draft.match(/^TASK_RELAY_REQUEST_[a-f0-9-]{36}(?=\n)/)?.[0];
    // Bounded composer inspection supports an explicit New after an extension
    // reload. It does not read history or infer authority from page content.
    let existingDraft;
    if(requestId&&draft.length<=220000){try{const context=JSON.parse(contextText(draft));if(context.capture&&typeof context.capture.content==='string')existingDraft={requestId,request:draft,url:here.href};}catch{}}
    return {url: here.href, adapter: 'chatgpt',existingDraft};
  }
  if (action === 'recover') {
    // Explicit recovery reads the latest loaded user turn only. Never infer a
    // ticket from an assistant suggestion or search through earlier chats.
    const users = messages().filter(row => row.role === 'user');
    const latest = users.at(-1), request = latest && messageText(latest);
    const requestId = request?.match(/^TASK_RELAY_REQUEST_[a-f0-9-]{36}(?=\s)/)?.[0];
    if (!requestId || request.length > 220000) throw Error('No recoverable Relay request was found in the latest message. Use manual import.');
    let context;
    try { context = JSON.parse(contextText(request)); } catch {
      const expansion=expandRequest(latest);
      if(expansion)return expansion;
      throw Error('The Relay request is incomplete. Use Options → Paste AI reply with the original selected text.');
    }
    const ticket = {requestId, request, url: here.href};
    const result = chatgptHandoff('response', ticket);
    if (result.handoffError) return result;
    return {...result, recoveredRequest: request, recoveredContext: context};
  }
  if (!/^TASK_RELAY_REQUEST_[a-f0-9-]{36}$/.test(payload.requestId || '') ||
      typeof payload.request !== 'string' || payload.request.length > 220000 ||
      !payload.request.startsWith(payload.requestId + '\n')) throw Error('The prepared request is invalid. Prepare analysis again.');
  const expected = new URL(payload.url);
  const newChat = expected.pathname === '/';
  if (expected.hostname !== 'chatgpt.com' || expected.protocol !== 'https:' ||
      (here.href !== expected.href && !(action === 'response' && newChat && /^\/c\/[^/]+\/?$/.test(here.pathname)))) {
    throw Error('The ChatGPT conversation changed. Return to the original chat or prepare a new request.');
  }
  const all = messages();
  const sent = all.filter(row => row.role === 'user' && normalize(messageText(row)) === normalize(payload.request));
  const tagged = all.filter(row => row.role === 'user' && normalize(messageText(row)).startsWith(payload.requestId + ' '));
  if (action === 'insert') {
    if (sent.length || tagged.length) throw Error('This request is already in the conversation. Use Get result from chat; it was not inserted again.');
    const marker=payload.requestId.replace('TASK_RELAY_REQUEST_','TASK_RELAY_RESPONSE_');
    if(all.some(row=>row.role==='assistant'&&text(row.el).split(/\r?\n/).some(line=>line.trim()===marker)))return {url:here.href,handoffError:'The matching Relay reply is already in this chat. Download it instead; nothing was inserted.',handoffCode:'reply_available'};
    if (streaming()) throw Error('ChatGPT is still responding. Wait before inserting the request.');
    const el = composer(), draft = value(el);
    if (normalize(draft) === normalize(payload.request)) return {url: here.href, inserted: true, reused: true};
    const replacement=payload.replaceDraft;
    const replacesOwnedDraft=replacement&&replacement.url===payload.url&&/^TASK_RELAY_REQUEST_[a-f0-9-]{36}$/.test(replacement.requestId||'')&&typeof replacement.request==='string'&&replacement.request.startsWith(replacement.requestId+'\n')&&normalize(draft)===normalize(replacement.request);
    if (draft.trim()&&!replacesOwnedDraft) throw Error('Your existing ChatGPT draft was preserved. Move it aside before using Relay.');
    // Attachments make an empty text box an existing draft too. Refuse known
    // attachment UI rather than sending Relay instructions with unrelated files.
    const scope = el.closest('form') || el.parentElement;
    if (scope && [...scope.querySelectorAll('[data-testid*="attachment"],[data-testid*="file"],button[aria-label^="Remove"]')].some(visible)) {
      throw Error('Your ChatGPT draft contains an attachment. Remove or send it before inserting Relay’s request.');
    }
    el.focus();
    if (el.tagName === 'TEXTAREA') {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, payload.request);
      el.dispatchEvent(new Event('input', {bubbles: true}));
    } else {
      const selection = window.getSelection(), range = document.createRange();
      range.selectNodeContents(el); selection.removeAllRanges(); selection.addRange(range);
      // The editor receives a normal edit (including its undo transaction).
      // Do not mutate innerHTML: that can desynchronize a controlled editor.
      if (!document.execCommand('insertText', false, payload.request)) throw Error('ChatGPT did not accept the draft insertion. Check the message box and use Copy request if needed.');
    }
    if (normalize(value(el)) !== normalize(payload.request)) throw Error('Draft insertion could not be confirmed. Check ChatGPT’s message box before retrying; Relay did not send anything.');
    return {url: here.href, inserted: true, reused: false};
  }
  if (action !== 'response') throw Error('Unsupported ChatGPT handoff action.');
  if (!sent.length && tagged.length) {
    // Expand only the uniquely identified submitted request. This changes its
    // display, never its text or the composer. A subsequent read still needs
    // the exact retained request; expansion cannot authorize an edited request.
    if (tagged.length === 1) {
      const expansion=expandRequest(tagged[0]);
      if(expansion)return expansion;
    }
    throw Error('Relay could not verify the submitted request. If you edited it, use Options → Paste AI reply.');
  }
  // Long pastes can become "Pasted text(...).txt" attachments. The file's
  // contents are not in the document. Only an explicit result read in the
  // retained destination may use the reply marker; never call this an exact
  // request verification, and never use it to authorize another insertion.
  const users = all.filter(row => row.role === 'user');
  const attached = users.flatMap(row => [...row.el.querySelectorAll('button')].filter(visible).filter(el => /^Pasted text(?:\s*\([^\r\n]*\))?\.txt$/.test((el.getAttribute('aria-label') || text(el)).trim())));
  const attachmentReply = !sent.length && !tagged.length && users.length === 1 && payload.allowAttachmentResponse === true && attached.length === 1;
  if (!sent.length && !attachmentReply) {
    if (attached.length) return {url:here.href,handoffError:'ChatGPT attached the pasted request. Copy its reply and use Paste AI reply; do not restore or resend.',handoffCode:'request_in_attachment'};
    return {url:here.href,handoffError:'Send the message in ChatGPT first.',handoffCode:value(composer()).trim()?'request_not_sent':'draft_missing'};
  }
  if (sent.length > 1) throw Error('Several matching requests were found. Import the intended response manually.');
  const following = all.slice(all.indexOf(attachmentReply ? users[0] : sent[0]) + 1);
  if (following.some(row => row.role === 'user')) throw Error('There is a later user message. Import the intended Relay response manually.');
  if (streaming()) throw Error('ChatGPT is still responding. Wait for it to finish, then get the result.');
  const answers = following.filter(row => row.role === 'assistant');
  if (answers.length !== 1) throw Error(answers.length ? 'Several response sections were found. Import the intended response manually.' : 'No response is available yet. Wait for ChatGPT to finish.');
  const body = answers[0].el.querySelector('.markdown') || answers[0].el;
  const marker = payload.requestId.replace('TASK_RELAY_REQUEST_', 'TASK_RELAY_RESPONSE_');
  const code = [...body.querySelectorAll('pre code,code[class*="CodeContent-"]')].filter(visible);
  let response = text(body);
  if (code.length) {
    const markerParagraph = [...body.querySelectorAll('p')].some(el => visible(el) && !el.closest('pre') && text(el).trim() === marker);
    if (!markerParagraph) throw Error('The response did not identify this Relay request. Use manual import after checking it.');
    if (code.length !== 1) throw Error('Several response blocks were found. Import the intended block manually.');
    // Markdown rendering removes fences and adds Copy/language controls. Read
    // code text directly and reconstruct the transport, never scrape those UI labels.
    response = marker+'\n```json\n'+code[0].textContent+'\n```';
  } else if (!response.split(/\r?\n/).some(line => line.trim() === marker)) {
    throw Error('The response did not identify this Relay request. Use manual import after checking it.');
  }
  if (new TextEncoder().encode(response).length > 240000) throw Error('The response is too large. Ask for a smaller result or import a bounded response file.');
  return {url: here.href, response, requestId: payload.requestId, requestVerification: attachmentReply ? 'attachment-response-marker' : 'exact-visible-request', messageId: answers[0].el.getAttribute('data-message-id') || answers[0].el.getAttribute('data-chatgpt-search-message-ids') || null};
  } catch (error) {
    return {url: location.href, handoffError: error.message || 'ChatGPT handoff failed. Check the chat before retrying.'};
  }
}
