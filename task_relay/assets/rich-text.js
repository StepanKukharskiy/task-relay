/* Render untrusted Markdown locally; no remote images, HTML widgets or scripts. */
function renderMarkdown(target, text) {
  target.classList.add('rich-text');
  if (!window.marked || !window.DOMPurify) { target.textContent = text; return; }
  const fragment = DOMPurify.sanitize(marked.parse(String(text), {gfm: true, breaks: false}), {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'del',
      'blockquote', 'ul', 'ol', 'li', 'pre', 'code', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a'],
    ALLOWED_ATTR: ['href', 'title', 'class', 'start'],
  });
  for (const link of fragment.querySelectorAll('a')) {
    // Relative links are not executable app actions and cannot load local APIs.
    if (!/^https?:\/\//i.test(link.getAttribute('href') || '')) link.removeAttribute('href');
    else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
  }
  target.replaceChildren(fragment);
  for (const code of target.querySelectorAll('pre code')) {
    const language = [...code.classList].find(name => name.startsWith('language-'))?.slice(9);
    if (window.hljs && language && hljs.getLanguage(language)) {
      // Highlighter takes text and escapes it; never highlight unsanitized HTML.
      code.innerHTML = hljs.highlight(code.textContent, {language, ignoreIllegals: true}).value;
    }
  }
}
