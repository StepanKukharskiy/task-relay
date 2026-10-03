/* Render untrusted Markdown locally; no remote images, HTML widgets or scripts. */
function renderMarkdown(target, text, options = {}) {
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
    const url = link.getAttribute('href') || '';
    if (!/^https?:\/\//i.test(url) || options.linkAllowed && !options.linkAllowed(url)) link.removeAttribute('href');
    else if (options.openLink) {
      link.onclick = event => { event.preventDefault(); event.stopPropagation(); options.openLink(url); };
    } else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
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

/* Copied prose occasionally escapes all its formatting. Repair display only;
   code, exact saved messages and outbound transport bytes remain untouched. */
function presentationMarkdown(text) {
  let fence = null;
  return String(text).split('\n').map(line => {
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      return line;
    }
    if (marker) { fence = marker[1]; return line; }
    return line.split(/(`+[^`\n]*`+)/).map((part,i) => {
      if (i % 2) return part;
      return part.replace(/&#(?:x20|32);|&nbsp;/gi,' ')
        .replace(/\\\*\\\*([^\n]+?)\\\*\\\*/g,'**$1**')
        .replace(/^(\s*)\\(-{3,})\s*$/,'$1$2');
    }).join('');
  }).join('\n');
}
