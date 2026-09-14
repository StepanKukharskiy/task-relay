/* App releases are independent of source-package update notices. */
(() => {
  function view(state) {
    const attempt = state?.attempt || {}, candidate = state?.candidate;
    const phase = attempt.phase;
    const busy = ['preparing', 'downloading', 'launching', 'installing', 'recovering'].includes(phase);
    const ready = phase === 'ready';
    const attention = ['interrupted', 'needs_attention'].includes(phase);
    let detail = state?.supported ? 'Check for a newer app version.' : state?.detail || 'Reading app update status…';
    if (state?.checked) detail = candidate ? `Update available: ${candidate.version}${candidate.channel === 'beta' ? ' beta' : ''}.` : 'No newer compatible app update is available on this channel.';
    if (phase === 'preparing') detail = 'Preparing the download… You can keep using Relay.';
    if (phase === 'downloading') detail = `Downloading and verifying ${attempt.version}… ${attempt.progress || 0}%`;
    if (ready) detail = `${attempt.version} is verified and ready. Finish running jobs before installing. Relay will close and restart; your saved data stays in place.`;
    if (['launching', 'installing'].includes(phase)) detail = `Installing ${attempt.version}… Relay will restart when ready.`;
    if (phase === 'recovering') detail = 'Recovering the previous app and checking its services…';
    if (phase === 'complete') detail = `Updated to ${attempt.version}.`;
    if (phase === 'rolled_back') detail = 'The previous app was restored. Your saved data was preserved.';
    if (phase === 'failed') detail = attempt.error || 'The download did not finish. You can check and download again.';
    if (attention) detail = attempt.error || 'This update needs recovery. It will not be repeated automatically.';
    return {detail, busy, ready, attention, check: !!state?.supported && !busy && !ready && !attention,
      download: !!state?.supported && !!candidate && !busy && !ready && !attention,
      recover: ready || attention};
  }
  let state, busy = false, timer, connected = false;
  const el = id => document.getElementById(id);
  const request = (path, value = {}) => window.__TAURI__.core.invoke('relay_request', {path, value});
  function render(value) {
    state = value;
    const model = view(value);
    el('app-update-summary').textContent = model.detail;
    el('app-update-heading').textContent = model.ready || model.download ? `App updates · ${value.attempt?.phase === 'ready' ? value.attempt.version : value.candidate.version} available` : 'App updates';
    el('app-update-notes').hidden = !value.candidate;
    el('app-update-notice').hidden = !(model.ready || model.download || model.attention);
    el('app-update-notice').textContent = model.attention ? 'Update needs attention' : 'Update available';
    el('app-update-check').disabled = busy || !model.check;
    el('app-update-beta').disabled = busy || !model.check;
    el('app-update-download').hidden = !model.download;
    el('app-update-download').disabled = busy;
    el('app-update-install').hidden = !model.ready;
    el('app-update-install').disabled = busy;
    el('app-update-recover').hidden = !model.recover;
    el('app-update-recover').disabled = busy;
    el('app-update-recover').textContent = model.ready ? 'Discard prepared update' : 'Recover previous app';
    if (typeof value.beta === 'boolean') el('app-update-beta').checked = value.beta;
    clearTimeout(timer);
    timer = setTimeout(() => load(!model.busy), model.busy ? 1500 : 3600000);
  }
  async function load(checkIfDue = false) {
    if (busy) return;
    try {
      render(await request('app-update-status'));
      if (checkIfDue && view(state).check && (!state.checked || Date.now() / 1000 - state.checked > 86400)) {
        await action('check', {beta: !!state.beta});
      }
    }
    catch (error) { el('app-update-summary').textContent = String(error); }
  }
  async function action(name, value) {
    if (busy) return;
    busy = true;
    render(state || {});
    el('app-update-summary').textContent = name === 'check' ? 'Checking app releases…' : name === 'download' ? 'Preparing the download…' : 'Preparing to restart Relay…';
    let result;
    try { result = await request('app-update-' + name, value); }
    catch (error) {
      busy = false;
      try { render(await request('app-update-status')); } catch (_) { render(state || {}); }
      el('app-update-summary').textContent = String(error);
      return;
    }
    busy = false; render(result);
  }
  function connect() {
    if (connected || !window.__TAURI__) return;
    connected = true;
    el('app-update-notice').onclick = () => {
      el('settings').open = true; el('app-updates-settings').open = true;
      el('app-updates-settings').scrollIntoView({block: 'nearest'});
    };
    el('app-update-notes').onclick = () => window.__TAURI__.core.invoke('companion_open', {target: 'app-releases'}).catch(error => { el('app-update-summary').textContent = String(error); });
    el('app-update-check').onclick = () => action('check', {beta: el('app-update-beta').checked});
    el('app-update-download').onclick = () => action('download', {id: state.candidate.id});
    el('app-update-install').onclick = () => action('install', {id: state.attempt.id});
    el('app-update-recover').onclick = () => action('recover', {id: state.attempt.id});
    load(true);
  }
  window.RelayAppUpdates = {view, connect};
})();
