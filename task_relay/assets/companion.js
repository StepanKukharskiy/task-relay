/* Desktop companion: connections and exact decisions, never a second inbox. */
const $ = id => document.getElementById(id);
const native = window.__TAURI__;
let snapshot = null;
let refreshing = false;
let mutating = false;
let pairingURL = null;
let cleanupManifest = null;
let handoff = null;
let firstRead = true;
let readFailed = false;
const submittedDecisions = new Set();
const keyURLs = {
  gemini: 'https://aistudio.google.com/apikey', openai: 'https://platform.openai.com/api-keys',
  qwen: 'https://www.alibabacloud.com/help/en/model-studio/get-api-key',
  deepseek: 'https://platform.deepseek.com/api_keys', openrouter: 'https://openrouter.ai/settings/keys'
};
const request = (path, value = {}) => native.core.invoke('relay_request', {path, value});
function message(text, error = false) {
  $('feedback').hidden = !text;
  $('feedback').textContent = text;
  $('feedback').classList.toggle('error', error);
}
function text(id, value) { $(id).textContent = value ?? ''; }
function openSettings(section) {
  if (['channels-settings', 'telegram-settings', 'messages-settings'].includes(section)) {
    $('channels-settings').open = true;
    if (section !== 'channels-settings') $(section).open = true;
    $(section).scrollIntoView({block: 'nearest'});
    return;
  }
  $('settings').open = true;
  if (section) {
    for (const child of $('settings').children) if (child.tagName === 'DETAILS') child.open = child.id === section;
  }
  (section ? $(section) : $('settings')).scrollIntoView({block: 'nearest'});
}
function providerFields() {
  const name = $('provider-name').value;
  $('provider-credentials').hidden = name === 'later';
  $('provider-key-link').href = keyURLs[name] || keyURLs.gemini;
  $('endpoint-field').hidden = name !== 'qwen';
}
let setupStep = null;
const setupHomes = new Map();
function renderSetup(info) {
  setupStep = RelaySetup.step(info);
  for (const id of ['provider-settings', 'telegram-settings']) {
    const form = $(id);
    if (!setupHomes.has(id)) {
      const marker = document.createComment(id + ' home');
      form.before(marker); setupHomes.set(id, marker);
    }
    if (setupStep?.form === id) {
      $('setup-form').append(form); form.open = true; form.classList.add('setup-inline');
    } else {
      if (form.classList.contains('setup-inline')) { setupHomes.get(id).after(form); form.open = false; }
      form.classList.remove('setup-inline');
    }
  }
  $('onboarding').hidden = !setupStep;
  $('home').hidden = !!setupStep;
  if (!setupStep) return;
  text('setup-title', setupStep.title);
  text('setup-progress', `Step ${setupStep.number} of 4 · AI → Telegram → Start → Pair`);
  text('setup-next', setupStep.detail);
  $('continue-setup').hidden = !!setupStep.form;
  $('continue-setup').disabled = mutating;
  text('continue-setup', setupStep.label || 'Continue');
}
async function nextSetup() {
  if (!snapshot) return;
  renderSetup(snapshot);
  if (!setupStep) return;
  if (setupStep.form) return $(setupStep.form).scrollIntoView({block: 'nearest'});
  if (setupStep.action === 'start') return change('service-start', {}, $('continue-setup'));
  if (setupStep.action === 'connect') return change('service-connect', {}, $('continue-setup'));
  if (setupStep.action === 'handoff') return prepareHandoff('relay');
  if (setupStep.action === 'troubleshoot') return openSettings('advanced-settings');
  if (setupStep.action === 'pair') {
    const result = await change('telegram', {}, $('continue-setup'));
    if (result?.pairing_url) {
      pairingURL = result.pairing_url;
      try { await native.opener.openUrl(pairingURL); } catch (error) { message(String(error), true); }
    }
  }
}
function render(info) {
  snapshot = info;
  const {setup, service = {}, messages = {}, decisions = {}} = info;
  const channels = info.channels || {};
  const policy = channels.policy;
  const paired = {telegram: setup.telegram.paired, messages: messages.paired};
  const pending = ['telegram', 'messages'].filter(c => paired[c] && !channels.runtime?.[c]);
  for (const channel of ['telegram', 'messages']) {
    const button = $('channel-' + channel);
    const enabled = !!policy?.enabled[channel];
    button.disabled = mutating || !channels.available || !paired[channel];
    button.setAttribute('aria-checked', String(enabled && !!paired[channel]));
    button.textContent = !paired[channel] ? 'Set up' : enabled ? 'On' : 'Off';
  }
  $('messaging-pause').disabled = mutating || !channels.available;
  text('messaging-pause', policy?.paused ? 'Resume messaging' : 'Pause all messaging');
  text('channels-summary', policy?.paused ? (pending.length ? 'Pause pending' : 'Paused') : policy ? `${Object.keys(paired).filter(c => paired[c] && policy.enabled[c]).length} enabled` : 'Setup needed');
  text('channel-enforcement', channels.error || (pending.length ? `Waiting for ${pending.join(' and ')} to confirm these controls. Older services need a restart; saved switches alone do not stop them.` : policy?.paused ? 'New requests and outgoing messages are paused. Running work continues.' : 'Changes apply before the next request or send. A message already being sent can finish.'));
  $('proactive-destination').disabled = mutating || !channels.available;
  if (policy) $('proactive-destination').value = policy.proactive;
  for (const option of $('proactive-destination').options) option.disabled = option.value !== 'none' && !paired[option.value];
  const connected = Object.keys(setup.providers).filter(name => setup.providers[name]);
  const providerReady = connected.length > 0 || setup.selected_provider === 'later';
  const ready = providerReady && setup.telegram.paired;
  text('version', 'Version ' + setup.version);
  text('status-title', service.error ? 'Connection needs attention' : service.healthy ? 'Relay is running' : service.loaded ? 'Checking Relay connection' : 'Relay is stopped');
  text('status-detail', service.error || (policy?.paused ? (pending.length ? 'Messaging pause is waiting for service confirmation. Check Channels.' : 'Messaging is paused. Work already started can continue.') : service.healthy ? 'Work in your enabled messengers. Manage delivery in Channels.' : service.detail));
  $('status-dot').className = 'dot ' + (service.healthy ? 'ready' : service.loaded || service.error ? 'attention' : '');
  $('open-conversation').disabled = !info.conversation?.url;
  $('service-action').hidden = !!service.error || service.owner === 'other';
  $('service-action').disabled = mutating || (!service.loaded && !setup.telegram.configured);
  text('service-action', service.loaded ? 'Stop Relay' : 'Start Relay');
  text('service-note', service.owner === 'other' ? 'Your existing service stays under its current installation until you choose a handoff in Settings.' : 'Closing this window leaves the service running. Stopping it does not undo work already performed.');
  text('provider-summary', connected.join(', ') || (setup.selected_provider === 'later' ? 'Existing agents' : 'Not connected'));
  if (firstRead && setup.selected_provider) $('provider-name').value = setup.selected_provider;
  providerFields();
  text('telegram-summary', setup.telegram.paired ? 'Paired' : setup.telegram.configured ? 'Pairing pending' : 'Not connected');
  $('telegram-token').disabled = setup.telegram.configured;
  text('telegram-save', setup.telegram.configured ? (setup.telegram.paired ? 'Check saved pairing' : 'Get pairing link') : 'Connect Telegram');
  const folders = $('folder-list');
  folders.replaceChildren();
  for (const folder of info.folders || []) {
    const row = document.createElement('div'); row.className = 'channel-card';
    const name = document.createElement('strong'); name.textContent = folder.name;
    const path = document.createElement('p'); path.className = 'path'; path.textContent = folder.path;
    const purpose = document.createElement('p'); purpose.className = 'hint'; purpose.textContent = folder.purpose;
    row.append(name, path, purpose); folders.append(row);
  }
  if (!info.folders?.length) folders.textContent = 'Folder information is unavailable. Refresh to try again.';
  text('ownership-detail', service.detail || service.error);
  $('connect-existing').hidden = !service.connectable;
  $('service-handoff').hidden = service.owner !== 'other' || !service.shared_data;
  text('data-location', 'Connection changes preserve saved tasks, pairing and artifact versions.');
  $('messages-action').hidden = !messages.managed;
  text('messages-action', messages.loaded ? 'Stop Messages connection' : 'Start Messages connection');
  $('messages-handoff').hidden = !messages.handoff_available;
  text('messages-summary', messages.error ? 'Needs attention' : messages.healthy ? 'Connected' : messages.loaded ? 'Needs attention' : messages.paired ? 'Stopped' : 'Optional');
  text('messages-detail', messages.detail || messages.error || 'No Messages connection found.');
  text('messages-limit', messages.uncertain ? `${messages.uncertain} uncertain deliveries need inspection. They will not be resent automatically.` : messages.paired ? 'Pairing is retained. macOS permissions may need to be granted again after a helper handoff.' : 'First-time Messages pairing remains a separate pilot setup. Telegram is the complete setup path.');
  const items = decisions.items || [];
  $('decisions').hidden = !items.length && !decisions.error;
  text('review-decisions', decisions.error || `Review ${items.reduce((n, item) => n + item.count, 0)} pending decisions…`);
  const diagnostics = $('diagnostics');
  diagnostics.replaceChildren();
  for (const check of setup.doctor.checks || []) {
    const row = document.createElement('p'); row.className = 'check';
    const label = document.createElement('strong'); label.textContent = check.check;
    const detail = document.createElement('span'); detail.textContent = check.detail;
    row.append(label, detail); diagnostics.append(row);
  }
  text('update-summary', setup.update.error || (setup.update.latest ? 'Latest cached release: ' + setup.update.latest : 'No release information cached.'));
  if (setup.setup_error) message(setup.setup_error, true);
  renderSetup(info);
  firstRead = false;
}
async function refresh() {
  if (refreshing || mutating) return;
  refreshing = true;
  $('refresh').disabled = true;
  try {
    render(await request('companion-status'));
    if (readFailed) message('Connection restored.');
    readFailed = false;
    $('grant-data-access').hidden = true;
  }
  catch (error) {
    readFailed = true;
    snapshot = null;
    $('home').hidden = false;
    $('onboarding').hidden = true;
    text('status-title', 'Could not read Relay');
    text('status-detail', 'Check local access, then refresh. Saved settings remain in place.');
    $('status-dot').className = 'dot attention';
    $('service-action').hidden = true;
    $('open-conversation').disabled = true;
    for (const id of ['channel-telegram', 'channel-messages', 'messaging-pause', 'proactive-destination']) $(id).disabled = true;
    $('grant-data-access').hidden = false;
    message(String(error), true);
  } finally { refreshing = false; $('refresh').disabled = false; }
}
async function change(action, value = {}, button = null) {
  if (mutating) return null;
  mutating = true;
  if (button) button.disabled = true;
  message('Working…');
  try {
    const result = await request(action, value);
    message(result.message || 'Saved.');
    return result;
  } catch (error) {
    message(String(error) + ' Check the current status before trying again; interrupted submissions are not automatically repeated.', true);
    return null;
  } finally {
    mutating = false;
    if (button) button.disabled = false;
    await refresh();
  }
}
async function openConversation() {
  try { await native.core.invoke('companion_open', {target: 'conversation'}); }
  catch (error) { message(String(error), true); }
}
async function reviewDecisions() {
  $('review').hidden = false;
  $('decision-detail').replaceChildren();
  const list = $('decision-list'); list.replaceChildren();
  try {
    const inbox = await request('approval-inbox');
    if (!inbox.items.length) { list.textContent = 'No pending local decisions.'; return; }
    for (const item of inbox.items) {
      const button = document.createElement('button'); button.className = 'row-link';
      button.textContent = `${item.title} · ${item.count}`;
      button.onclick = () => loadDecision(item.task_id); list.append(button);
    }
    $('review').scrollIntoView({block: 'start'});
  } catch (error) { message(String(error), true); }
}
async function loadDecision(taskId) {
  try {
    const result = await request('approval-detail', {task_id: taskId});
    const target = $('decision-detail'); target.replaceChildren();
    const title = document.createElement('h2'); title.textContent = result.title; target.append(title);
    for (const card of result.approvals) {
      const key = taskId + ':' + card.token + ':' + card.fingerprint;
      const box = document.createElement('div'); box.className = 'review-card';
      const details = document.createElement('details');
      const heading = document.createElement('summary'); heading.textContent = card.title;
      const review = document.createElement('pre'); review.textContent = card.review;
      details.append(heading, review); box.append(details);
      const actions = document.createElement('div'); actions.className = 'actions';
      const answer = document.createElement('textarea'); answer.placeholder = 'Your answer';
      answer.setAttribute('aria-label', 'Answer this request'); answer.maxLength = 4000;
      if (card.can_answer) box.append(answer);
      const buttons = [];
      const submit = async (allow) => {
        if (mutating || submittedDecisions.has(key)) return;
        if (allow && card.can_answer && !answer.value.trim()) return message('Enter an answer first.', true);
        submittedDecisions.add(key); buttons.forEach(button => button.disabled = true);
        const value = {task_id: taskId, token: card.token, fingerprint: card.fingerprint, allow: allow && !card.can_answer};
        if (allow && card.can_answer) value.answer = answer.value;
        const response = await change('task-approval-decide', value);
        if (response) await reviewDecisions();
        else message('The decision could not be confirmed. Inspect its receipt in the originating app; this card will not submit again.', true);
      };
      if (card.can_allow || card.can_answer) {
        const allow = document.createElement('button'); allow.textContent = card.can_answer ? 'Send answer' : 'Allow once';
        allow.disabled = true; allow.onclick = () => submit(true); actions.append(allow); buttons.push(allow);
        details.addEventListener('toggle', () => { allow.disabled = !details.open || submittedDecisions.has(key); });
      }
      if (card.can_deny) {
        const deny = document.createElement('button'); deny.textContent = 'Deny'; deny.disabled = submittedDecisions.has(key);
        deny.onclick = () => submit(false); actions.append(deny); buttons.push(deny);
      }
      box.append(actions); target.append(box);
    }
    if (!result.approvals.length) target.append(document.createTextNode('This decision is no longer pending.'));
  } catch (error) { message(String(error), true); }
}
async function prepareHandoff(channel) {
  const result = await change('handoff-prepare', {channel});
  if (!result) return;
  handoff = result;
  $('handoff-apply').disabled = false;
  text('handoff-text', result.review);
  $('handoff-review').hidden = false; $('handoff-review').scrollIntoView({block: 'start'});
}
$('refresh').onclick = refresh;
$('grant-data-access').onclick = async () => {
  try {
    const expected = await native.core.invoke('companion_data_location');
    const selected = await native.dialog.open({directory: true, multiple: false, canCreateDirectories: false,
      defaultPath: expected, title: 'Allow Task Relay to read its existing data folder'});
    if (!selected) return;
    if (selected.replace(/\/$/, '') !== expected.replace(/\/$/, '')) return message('Choose the existing data folder: ' + expected + '. The saved connection was not changed.', true);
    await refresh();
  } catch (error) { message(String(error), true); }
};
$('open-conversation').onclick = openConversation;
$('continue-setup').onclick = nextSetup;
$('provider-name').onchange = providerFields;
$('review-decisions').onclick = reviewDecisions;
$('close-review').onclick = () => { $('review').hidden = true; };
$('service-action').onclick = () => {
  if (snapshot?.service && !snapshot.service.error) change(snapshot.service.loaded ? 'service-stop' : 'service-start', {}, $('service-action'));
};
async function updateChannels(values, button) {
  if (!snapshot?.channels?.policy) return;
  await change('channel-update', {revision: snapshot.channels.policy.revision, ...values}, button);
}
for (const channel of ['telegram', 'messages']) $('channel-' + channel).onclick = () =>
  updateChannels({channel, enabled: !snapshot?.channels?.policy?.enabled[channel]}, $('channel-' + channel));
$('messaging-pause').onclick = () => updateChannels({paused: !snapshot?.channels?.policy?.paused}, $('messaging-pause'));
$('proactive-destination').onchange = () => updateChannels({proactive: $('proactive-destination').value}, $('proactive-destination'));
$('provider-form').onsubmit = async event => {
  event.preventDefault();
  const values = {name: $('provider-name').value, key: $('provider-key').value, model: $('provider-model').value, endpoint: $('provider-endpoint').value};
  if (values.name === 'later') values.key = values.model = values.endpoint = '';
  const result = await change('provider', values, event.submitter);
  $('provider-key').value = '';
  if (result && snapshot) renderSetup(snapshot);
};
$('telegram-form').onsubmit = async event => {
  event.preventDefault();
  const result = await change('telegram', {token: $('telegram-token').value}, event.submitter);
  $('telegram-token').value = '';
  if (result) { pairingURL = result.pairing_url; $('pair-telegram').hidden = !pairingURL; }
};
$('pair-telegram').onclick = async () => {
  if (pairingURL) try { await native.opener.openUrl(pairingURL); } catch (error) { message(String(error), true); }
};
$('connect-existing').onclick = () => change('service-connect', {}, $('connect-existing'));
$('messages-action').onclick = () => change(snapshot?.messages?.loaded ? 'messages-stop' : 'messages-start', {}, $('messages-action'));
for (const [id, target] of [['messages-open', 'messages'], ['messages-permissions', 'permissions'], ['folder-permissions', 'permissions']]) {
  $(id).onclick = async () => { try { await native.core.invoke('companion_open', {target}); } catch (error) { message(String(error), true); } };
}
$('service-handoff').onclick = () => prepareHandoff('relay');
$('messages-handoff').onclick = () => prepareHandoff('messages');
$('handoff-cancel').onclick = () => { handoff = null; $('handoff-review').hidden = true; };
$('handoff-apply').onclick = async () => {
  if (!handoff) return;
  const exact = handoff; handoff = null; $('handoff-apply').disabled = true;
  const result = await change('handoff-apply', {id: exact.id, digest: exact.digest});
  if (result) $('handoff-review').hidden = true;
  else message('The handoff did not confirm completion. Inspect recovery status in Settings; do not submit the same handoff again.', true);
};
$('handoff-history').onclick = async () => {
  try {
    const result = await request('handoff-status');
    const target = $('handoff-receipts'); target.replaceChildren();
    if (!result.items.length) target.textContent = 'No service handoffs recorded.';
    for (const item of result.items) {
      const details = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = `${item.channel} · ${item.phase}`;
      const description = document.createElement('pre'); description.textContent = item.detail + '\n' + (item.review || '');
      details.append(summary, description);
      if (item.channel !== 'unknown' && ['complete', 'stopping', 'switching', 'starting', 'restoring', 'uncertain'].includes(item.phase)) {
        const restore = document.createElement('button'); restore.textContent = 'Restore this prior service definition';
        restore.onclick = async () => { restore.disabled = true; await change('handoff-restore', {id: item.id}); $('handoff-history').click(); };
        details.append(restore);
      }
      target.append(details);
    }
  } catch (error) { message(String(error), true); }
};
$('update-check').onclick = () => change('update-check', {}, $('update-check'));
let usageLoading = false;
$('usage-settings').ontoggle = async () => {
  if (!$('usage-settings').open || usageLoading) return;
  usageLoading = true;
  text('usage-summary', 'Loading usage…');
  try {
    const result = await request('usage-summary');
    text('usage-summary', `${result.tokens.relay_total == null ? 'Unknown' : result.tokens.relay_total.toLocaleString()} recorded Relay tokens · 7 days. ${result.tokens.relay_unmeasured ?? 0} unmeasured records. Storage ${result.storage.complete ? '' : 'at least '}${(result.storage.bytes / 1073741824).toFixed(2)} GiB. This is not a bill or account quota.`);
  } catch (error) { text('usage-summary', 'Usage could not be read. Close and reopen Usage to try again.'); }
  finally { usageLoading = false; }
};
$('cleanup-preview').onclick = async () => {
  cleanupManifest = null; $('cleanup-review').hidden = true;
  const result = await change('cleanup-preview', {}, $('cleanup-preview'));
  if (result) { cleanupManifest = result.manifest; text('cleanup-summary', `${result.files} verified disposable files · ${(result.bytes / 1048576).toFixed(1)} MiB. Unique backups and work artifacts are retained.`); $('cleanup-review').hidden = false; }
};
$('cleanup-apply').onclick = async () => {
  if (!cleanupManifest) return;
  const manifest = cleanupManifest; cleanupManifest = null;
  await change('cleanup-apply', {manifest}, $('cleanup-apply')); $('cleanup-review').hidden = true;
};
document.addEventListener('click', async event => {
  const link = event.target.closest('a'); if (!link) return;
  event.preventDefault(); try { await native.opener.openUrl(link.href); } catch (error) { message(String(error), true); }
});
window.addEventListener('unhandledrejection', event => message(String(event.reason), true));
if (native) {
  native.event.listen('companion-navigate', async ({payload}) => {
    if (payload === 'channels') return openSettings('channels-settings');
    if (payload === 'pause-messaging') {
      await refresh();
      if (snapshot?.channels?.policy && !snapshot.channels.policy.paused) await updateChannels({paused: true}, $('messaging-pause'));
      return openSettings('channels-settings');
    }
    if (payload === 'conversation') return openConversation();
    if (payload === 'review') return reviewDecisions();
    if (payload === 'settings') return openSettings();
    await refresh(); window.scrollTo(0, 0);
  });
  refresh();
  setInterval(() => { if (!document.hidden && !mutating && !readFailed) refresh(); }, 20000);
} else {
  message('Open Task Relay.app to connect your services. This page is a desktop companion, not a standalone installer.', true);
  document.querySelectorAll('button, input, select').forEach(element => element.disabled = true);
}
