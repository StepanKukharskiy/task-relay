/* Native setup and saved sessions. No task or browser is started here. */
(() => {
  const $ = id => document.getElementById(id);
  const request = (path, value = {}) => window.__TAURI__.core.invoke('relay_request', {path, value});
  let selected = null, revision = 0, listRevision = 0, next = null, busy = false;
  const status = value => { $('computer-sessions-feedback').textContent = value; };
  let checkingSetup = false;
  async function checkSetup(prompt = false) {
    if (checkingSetup) return;
    checkingSetup = true;
    const buttons = [$('computer-setup-check'), $('computer-permissions-request')];
    buttons.forEach(b => b.disabled = true);
    $('computer-setup-detail').textContent = prompt ? 'Requesting window permissions from macOS…' : 'Checking helper and native permissions…';
    try {
      const value = await request(prompt ? 'computer-request-permissions' : 'computer-setup-status');
      $('computer-setup-summary').textContent = value.available ? 'Helper available' : 'Needs setup';
      $('computer-helper-path').textContent = value.helper || '';
      $('computer-setup-detail').textContent = value.available
        ? `Window observation: Accessibility ${value.permissions.accessibility ? 'granted' : 'not granted'}; Screen Recording ${value.permissions.screen_recording ? 'granted' : 'not granted'}; session ${value.permissions.session_unlocked ? 'unlocked' : 'locked'}. Background Safari Automation is checked when an approved task starts. After changing permissions, check setup again.`
        : value.error || 'The native helper is unavailable.';
    } catch (error) {
      $('computer-setup-summary').textContent = 'Check failed';
      $('computer-setup-detail').textContent = String(error) + ' No task was started. Check setup again after inspecting macOS settings.';
    } finally { checkingSetup = false; buttons.forEach(b => b.disabled = false); }
  }
  $('computer-setup-check').onclick = () => checkSetup();
  $('computer-permissions-request').onclick = () => checkSetup(true);
  for (const [id,target] of [['computer-automation-settings','computer-automation'],['computer-accessibility-settings','computer-accessibility'],['computer-screen-settings','computer-screen']]) {
    $(id).onclick = async () => { try { await window.__TAURI__.core.invoke('companion_open', {target}); } catch (error) { $('computer-setup-detail').textContent = String(error); } };
  }
  function node(tag, text) { const item = document.createElement(tag); item.textContent = text; return item; }
  function saved(label, value) {
    const item = document.createElement('details');
    item.append(node('summary', label), node('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
    return item;
  }
  function clearDetail() { selected = null; revision++; $('computer-session-detail').replaceChildren(); }
  async function listing(more = false) {
    const ticket = ++listRevision;
    if (!more) clearDetail();
    try {
      const result = await request('computer-sessions', {offset: more ? next : 0});
      if (ticket !== listRevision) return;
      const rows = result.items.map(item => {
        const button = node('button', `${item.request_excerpt} · ${item.state}`);
        button.type = 'button'; button.className = 'row-link';
        button.onclick = () => show(item.id);
        return button;
      });
      if (more) $('computer-sessions-list').append(...rows);
      else $('computer-sessions-list').replaceChildren(...rows);
      next = result.next_offset;
      $('computer-sessions-more').hidden = next === null;
      status(result.total ? `${result.total} saved session(s). Select one to inspect its current state.` : 'No saved Safari sessions at this data location.');
    } catch (error) { if (ticket === listRevision) status(String(error)); }
  }
  async function show(id) {
    if (busy) return;
    selected = id;
    const ticket = ++revision;
    $('computer-session-detail').replaceChildren();
    try {
      const view = await request('computer-session-detail', {id});
      if (ticket !== revision || selected !== id) return;
      render(view);
    } catch (error) { if (ticket === revision) status(String(error)); }
  }
  function render(view) {
    const panel = $('computer-session-detail');
    panel.className = 'review-card';
    panel.replaceChildren(node('h3', `Session ${view.state}`), node('p', `Job ${view.job} · Session ${view.id}`),
      saved('Exact approved request', view.exact_request), saved('Approved target, URLs and actions', view.spec),
      saved('Helper build identity', view.helper), node('p', `Last recorded URL: ${view.current_url}`));
    if (view.unresolved) panel.append(node('p', `${view.unresolved} action(s) have an unresolved outcome. Cancel does not resolve them or authorize a retry.`));
    panel.append(saved('Action receipts', view.actions), node('p', view.evidence_note),
      saved(`Recent decisions (${Math.min(view.decision_count, 20)} of ${view.decision_count}; notes excerpted)`, view.recent_decisions));
    const buttons = [];
    if (view.can_pause || view.can_cancel) {
      const label = node('label', 'Decision note'); label.htmlFor = 'computer-session-note';
      const note = document.createElement('textarea'); note.id = 'computer-session-note'; note.maxLength = 4000;
      panel.append(label, note);
      const actions = node('div', ''); actions.className = 'actions';
      for (const [kind, title] of [['pause', 'Pause further actions'], ['cancel', 'Cancel further actions']]) {
        if (!view['can_' + kind]) continue;
        const button = node('button', title); button.type = 'button'; button.disabled = true;
        button.onclick = async () => {
          if (busy || !note.value.trim()) return;
          busy = true; buttons.forEach(b => { b.disabled = true; }); note.disabled = true;
          const ticket = ++revision;
          try {
            const result = await request('computer-session-control', {id: view.id, kind,
              fingerprint: view.fingerprint, note: note.value});
            if (ticket === revision && selected === view.id) render(result);
            status('Decision saved. An action already started may finish; refresh to inspect its receipt.');
          } catch (error) {
            // Never automatically retry a possibly committed decision with stale authority.
            if (ticket === revision) { clearDetail(); status(String(error) + ' Refresh to inspect saved state.'); }
          } finally { busy = false; }
        };
        buttons.push(button); actions.append(button);
      }
      panel.append(actions);
      note.addEventListener('input', () => buttons.forEach(b => { b.disabled = busy || !note.value.trim(); }));
    }
  }
  $('computer-sessions-open').onclick = () => { window.RelayWorkspace?.navigate('sessions'); $('computer-sessions-panel').hidden = false; listing(); };
  $('computer-sessions-close').onclick = () => { $('computer-sessions-panel').hidden = true; clearDetail(); listRevision++; window.RelayWorkspace?.navigate('jobs'); };
  $('computer-sessions-refresh').onclick = () => { if (!busy) listing(); };
  $('computer-sessions-more').onclick = () => { if (!busy && next !== null) listing(true); };
  window.RelayComputerSessions = {connect: async () => {
    try {
      const result = await request('computer-sessions');
      $('computer-sessions-open').hidden = !result.total;
    } catch (_) { $('computer-sessions-open').hidden = true; }
  }};
})();
