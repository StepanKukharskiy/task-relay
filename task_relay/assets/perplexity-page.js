/* Runs in an isolated extension world, never accepting instructions from page content. */
(() => {
  'use strict';
  if (globalThis.taskRelayPerplexityInstalled) return;
  globalThis.taskRelayPerplexityInstalled = true;
  const visible = element => !!(element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');
  const label = element => element.getAttribute('aria-label') || element.getAttribute('title') || element.textContent.trim();
  const buttons = (name, exact = true) => [...document.querySelectorAll('button,[role="button"]')]
    .filter(e => visible(e) && (exact ? label(e) === name : label(e).startsWith(name)));
  const boxes = () => [...document.querySelectorAll('textarea,[contenteditable="true"][role="textbox"]')].filter(visible);
  const value = box => box.tagName === 'TEXTAREA' ? box.value : box.innerText;
  function url() {
    const u = new URL(location.href);
    if (u.protocol !== 'https:' || !['www.perplexity.ai', 'perplexity.ai'].includes(u.host) ||
        u.search || u.hash || !/^\/(?:search\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?$/.test(u.pathname)) {
      throw new Error('The worker tab left ordinary Perplexity Search.');
    }
    u.hostname = 'www.perplexity.ai';
    return u.href;
  }
  function snapshot() {
    const canonical = url();
    const root = document.querySelector('main,[role="main"]');
    if (!root) throw new Error('Perplexity conversation region is not recognized.');
    function rendered(node) {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent;
      if (node.nodeType !== Node.ELEMENT_NODE || !visible(node) ||
          node.matches('nav,aside,[role="navigation"],textarea,input,[contenteditable],script,style')) return '';
      const body = [...node.childNodes].map(rendered).join('');
      if (node.tagName === 'A' && /^https?:/.test(node.href)) return body + ' (' + node.href + ')';
      return body + (/^(P|DIV|LI|TR|H[1-6]|SECTION|ARTICLE|BR)$/.test(node.tagName) ? '\n' : '');
    }
    const text = rendered(root).replace(/\n{3,}/g, '\n\n').trim();
    if (new TextEncoder().encode(text).length > 250000) throw new Error('Conversation exceeds the text limit.');
    const box = boxes();
    const search = buttons('Search');
    const queries = buttons('Edit query').length;
    const answers = buttons('Copy').length;
    let blocked = '';
    if (/just a moment|verify you are human|security verification/i.test(document.title) ||
        [...document.querySelectorAll('iframe')].some(e => /challenges\.cloudflare\.com/.test(e.src))) {
      blocked = 'Browser verification requires your attention. No automatic retry.';
    } else if (!buttons('Profile avatar', false).length || buttons('Sign In').length) {
      blocked = 'Sign in to Perplexity in this browser first.';
    } else if ([...document.querySelectorAll('[role="dialog"],dialog[open]')].some(visible)) {
      blocked = 'Resolve the visible Perplexity dialog manually.';
    } else if (box.length !== 1) {
      blocked = 'The Search input is not uniquely recognized.';
    } else if (value(box[0]).trim()) {
      blocked = 'An existing draft was found; it was not overwritten.';
    } else if (search.length !== 1 || search[0].getAttribute('aria-pressed') !== 'true') {
      blocked = 'Select ordinary Search mode. Computer and other modes are outside this connection.';
    }
    return {url: canonical, text, queries, answers, blocked,
      ready: !blocked && queries === answers && !buttons('Stop response', false).length};
  }
  async function submit(message) {
    if (typeof message.prompt !== 'string' || !message.prompt.trim() || message.prompt.length > 12000) {
      throw new Error('Invalid research prompt.');
    }
    const before = snapshot();
    if (!before.ready || JSON.stringify(before) !== JSON.stringify(message.baseline)) {
      throw new Error(before.blocked || 'Perplexity changed before submission. No submit click was sent.');
    }
    const box = boxes()[0];
    box.focus();
    if (box.tagName === 'TEXTAREA') {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(box, message.prompt);
    } else {
      box.textContent = message.prompt;
    }
    box.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: message.prompt}));
    await new Promise(resolve => setTimeout(resolve, 100));
    if (url() !== before.url || buttons('Edit query').length !== before.queries ||
        buttons('Copy').length !== before.answers || buttons('Stop response', false).length) {
      throw new Error('The conversation changed while entering the prompt. No submit click was sent.');
    }
    if (value(box) !== message.prompt || !box.isConnected) throw new Error('The exact prompt could not be entered.');
    const submit = buttons('Submit');
    const search = buttons('Search');
    if (submit.length !== 1 || submit[0].disabled || search.length !== 1 ||
        search[0].getAttribute('aria-pressed') !== 'true' ||
        [...document.querySelectorAll('[role="dialog"],dialog[open]')].some(visible)) {
      throw new Error('Search submission controls changed. The draft was retained without submitting.');
    }
    submit[0].click(); // Exactly one submission attempt. No synthetic Enter or retry.
    return true;
  }
  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id || sender.tab || message?.relay !== true) return;
    if (message.action === 'snapshot') return Promise.resolve(snapshot());
    if (message.action === 'submit') return submit(message);
    return Promise.reject(new Error('Unsupported Perplexity operation.'));
  });
})();
