/* Injected on explicit Keep only. No listeners, fetches, observers or page writes. */
export function taskRelayCapture(selectionOnly=false) {
  try {
  // Raw capture budget is separate from each AI request's smaller budget.
  const LIMIT = 300000;
  function excluded(el) {
    // aria-hidden/inert can mark visually rendered citation labels and URLs.
    // Actual visibility and form boundaries determine what can be captured.
    return !!el.closest('script,style,noscript,nav,header,footer,aside,form,input,textarea,select,button,.sr-only,.visually-hidden,.screen-reader-only,[contenteditable]:not([contenteditable="false"]),[hidden]');
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
      if (length > LIMIT) throw new Error('This page exceeds 300,000 characters. Select a smaller excerpt; nothing was truncated.');
    }
    return chunks.join('\n');
  }
  const selection = window.getSelection();
  const selected = selection && !selection.isCollapsed;
  if(selectionOnly&&!selected)throw new Error('Select text on the page first.');
  let selectedContent, selectionFiltered=false;
  if (selected) {
    const parts=[];
    function block(el) {
      for(let node=el;node&&node!==document.body;node=node.parentElement) {
        const display=getComputedStyle(node).display;
        if(display!=='contents'&&!display.startsWith('inline'))return node;
      }
      return document.body;
    }
    for (let i = 0; i < selection.rangeCount; i++) {
      const range = selection.getRangeAt(i);
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if(!range.intersectsNode(node))continue;
        // Intersections may touch an unselected endpoint. Clip before checking
        // controls or reading text so adjacent fields are not false positives.
        const clipped=document.createRange();clipped.selectNodeContents(node);
        if(clipped.compareBoundaryPoints(0,range)<0)clipped.setStart(range.startContainer,range.startOffset);
        if(clipped.compareBoundaryPoints(2,range)>0)clipped.setEnd(range.endContainer,range.endOffset);
        if(clipped.collapsed)continue;
        const el=node.parentElement,text=clipped.toString();
        if(!el||!visible(el)){if(text.trim())selectionFiltered=true;continue;}
        if(text.trim()&&el.closest('form,input,textarea,select,[contenteditable]:not([contenteditable="false"])')) {
          throw new Error('Select message or article text, not an input field.');
        }
        if(excluded(el)){if(text.trim())selectionFiltered=true;continue;}
        const owner=block(el),previous=parts.at(-1);
        parts.push({text:(previous&&previous.owner!==owner?'\n':'')+text,owner});
      }
    }
    // Keep browser selection formatting when no filtering is needed. Otherwise
    // project only clipped visible text, retaining paragraph boundaries; never
    // remove hidden strings by value (they may also appear in valid evidence).
    if(!parts.some(part=>part.text.trim()))throw new Error('No readable text here. Highlight document text and try again.');
    selectedContent=selectionFiltered?parts.map(part=>part.text).join(''):selection.toString();
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
  const content = selected ? selectedContent : messages.length ? messages.map(row => `${row.role}:\n${read(row.el)}`).join('\n\n') : read(document.querySelector('main,[role="main"],article') || document.body);
  if (!content.trim()) throw new Error('No readable text here. Highlight document text and try again.');
  if (content.length > LIMIT) throw new Error('Capture exceeds 300,000 characters. Select a smaller excerpt; nothing was truncated.');
  const limits = ['Only text currently present in the main document was captured. Unloaded messages, frames, images and files are excluded.'];
  if(selectionFiltered)limits.push('Hidden text and interface controls crossed by the selection were excluded; visible text keeps its selected boundaries.');
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
