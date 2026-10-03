/* Injected on explicit Keep only. No listeners, fetches, observers or page writes. */
export function taskRelayCapture(selectionOnly=false) {
  try {
  const LIMIT = 60000;
  function excluded(el) {
    // aria-hidden/inert can mark visually rendered citation labels and URLs.
    // Actual visibility and form boundaries determine what can be captured.
    return !!el.closest('script,style,noscript,nav,header,footer,aside,form,input,textarea,select,button,h4.sr-only,[contenteditable="true"],[hidden]');
  }
  function visible(el) {
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
    }
    return el.getClientRects().length > 0;
  }
  function read(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const chunks = []; let node, length=0;
    while ((node = walker.nextNode())) {
      const el = node.parentElement;
      if (!el || excluded(el) || !visible(el) || !node.textContent.trim()) continue;
      chunks.push(node.textContent.trim());
      length+=node.textContent.trim().length+1;
      if (length > LIMIT) throw new Error('This page exceeds 60,000 characters. Select a smaller excerpt; nothing was truncated.');
    }
    return chunks.join('\n');
  }
  const selection = window.getSelection();
  const selected = selection && !selection.isCollapsed;
  if(selectionOnly&&!selected)throw new Error('Select text in your chat first.');
  if (selected) {
    for (let i = 0; i < selection.rangeCount; i++) {
      const range = selection.getRangeAt(i);
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (node.textContent.trim() && range.intersectsNode(node) && (excluded(node.parentElement) || !visible(node.parentElement))) {
          throw new Error('Selection includes hidden content or a form. Select visible document text only.');
        }
      }
    }
  }
  const host = location.hostname;
  const adapters = [
    {site: 'chatgpt', hosts: ['chatgpt.com'], selector: '[data-message-author-role]', role: el => el.getAttribute('data-message-author-role')},
    {site: 'claude', hosts: ['claude.ai'], selector: '[data-testid="user-message"],.font-claude-response', role: el => el.matches('[data-testid="user-message"]') ? 'user' : 'assistant'},
    {site: 'gemini', hosts: ['gemini.google.com'], selector: 'user-query,model-response', role: el => el.tagName.toLowerCase() === 'user-query' ? 'user' : 'assistant'},
    {site: 'perplexity', hosts: ['www.perplexity.ai','perplexity.ai'], selector: '[data-testid="user-query"],[data-testid="answer"]', role: el => el.matches('[data-testid="user-query"]') ? 'user' : 'assistant'}
  ];
  const adapter = adapters.find(a => a.hosts.includes(host));
  let messages = !selected && adapter ? [...document.querySelectorAll(adapter.selector)].filter(el => visible(el) && !excluded(el)).map(el => ({el,role:adapter.role(el)})) : [];
  if (!selected && adapter?.site === 'chatgpt' && !messages.length) {
    messages = [...document.querySelectorAll('[data-turn-key] h4.sr-only')].map(heading => ({el:heading.parentElement,role:heading.getAttribute('data-conversation-role') === 'assistant' ? 'assistant' : heading.textContent.trim() === 'You said:' ? 'user' : null})).filter(row => row.role && visible(row.el) && !excluded(row.el));
  }
  const content = selected ? selection.toString() : messages.length ? messages.map(row => `${row.role}:\n${read(row.el)}`).join('\n\n') : read(document.querySelector('main,[role="main"],article') || document.body);
  if (!content.trim()) throw new Error('No readable text here. Highlight document text and try again.');
  if (content.length > LIMIT) throw new Error('Capture exceeds 60,000 characters. Select a smaller excerpt; nothing was truncated.');
  const limits = ['Only text currently present in the main document was captured. Unloaded messages, frames, images and files are excluded.'];
  if (adapter && !selected && !messages.length) limits.push('Conversation markup was not recognized; generic visible text was used. Message roles are unavailable.');
  const url = new URL(location.href);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw new Error('Use a regular http(s) webpage without credentials in its address.');
  return {source_type: selected ? 'selection' : adapter ? 'conversation' : 'page', url: url.href,
    title: document.title || host, [selected ? 'selected_content' : 'extracted_content']: content,
    source_metadata: {adapter: selected ? 'selection' : messages.length ? adapter.site : 'generic', captured_at: new Date().toISOString(), limitations: limits}};
  } catch (error) {
    // Chrome can lose a thrown injected-script error and return no result.
    return {captureError: error.message || 'Could not read the selected text.'};
  }
}
