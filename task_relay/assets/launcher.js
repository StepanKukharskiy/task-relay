const root = location.pathname;
const $ = id => document.getElementById(id);
const nativeDesktop = Boolean(window.__TAURI__?.core?.invoke);
if (nativeDesktop) {
  window.addEventListener('error', event => {
    const target = document.getElementById('desktop-feedback');
    if (target) {
      target.textContent = 'Desktop page error: ' + event.message;
      target.hidden = false;
    }
  });
  window.addEventListener('unhandledrejection', event => {
    const target = document.getElementById('desktop-feedback');
    if (target) {
      target.textContent = 'Desktop page error: ' + String(event.reason);
      target.hidden = false;
    }
  });
}
let selectedTask = null;
let pendingInstruction = null;
let selectedFile = null;
let taskCanSend = false;
let taskCanCreate = false;
let pendingCreation = null;
let activeTab = null;
let autoTabPending = true;
let setupReady = null;
let selectedPlan = null;
let activePlan = null;
let pendingPlan = null;
let planParentId = null;
let planCanCreate = false;
let cleanupManifest = null;
let workflowOffset = null;
let savedJobs = [];
const appSections = ['tasks', 'workflows', 'tools', 'usage', 'setup', 'system'];
const openedPlanDocuments = new Set();
const urls = {
  gemini: 'https://aistudio.google.com/apikey',
  openai: 'https://platform.openai.com/api-keys',
  qwen: 'https://www.alibabacloud.com/help/en/model-studio/get-api-key',
  deepseek: 'https://platform.deepseek.com/api_keys',
  openrouter: 'https://openrouter.ai/settings/keys'
};

function feedback(id, message, error = false) {
  const target = $(id);
  target.textContent = message;
  target.classList.toggle('error', error);
}

function state(id, ready) {
  const target = $(id + '-state');
  target.textContent = ready ? '✓' : '·';
  target.classList.toggle('ready', ready);
  const pill = $(id + '-pill');
  if (pill) {
    pill.textContent = ready ? 'Saved' : 'To do';
    pill.classList.toggle('waiting', !ready);
  }
}

function checkItem(name, status, detail) {
  const row = document.createElement('div');
  row.className = 'check-item';
  const mark = document.createElement('span');
  mark.className = 'check-marker ' + (status === 'ok' ? 'ok' : status === 'fail' ? 'fail' : '');
  mark.textContent = status === 'ok' ? '✓' : status === 'fail' ? '!' : '·';
  const text = document.createElement('div');
  const label = document.createElement('strong');
  label.textContent = name;
  const small = document.createElement('small');
  small.textContent = detail;
  text.append(label, small);
  row.append(mark, text);
  return row;
}

function showTab(name, userSelected = false) {
  if (!nativeDesktop || !appSections.includes(name)) return;
  activeTab = name;
  document.title = 'Task Relay · ' + (name === 'tasks' ? 'Jobs' : name === 'tools' ? 'Automations & tools' : name[0].toUpperCase() + name.slice(1));
  document.body.dataset.section = name;
  if (name === 'workflows') refreshWorkflowLibrary();
  if (name === 'tools') refreshTools();
  if (name === 'usage') refreshUsage();
  if (userSelected) autoTabPending = false;
  for (const tab of appSections) {
    const selected = tab === name;
    $('app-' + tab + '-panel').hidden = !selected;
    $('tab-' + tab).setAttribute('aria-selected', String(selected));
    $('tab-' + tab).tabIndex = selected ? 0 : -1;
  }
  window.scrollTo(0, 0);
}

function syncSetupSteps(ready) {
  if (setupReady === null || ready.some((value, index) => value && !setupReady[index])) {
    const next = ready.findIndex(value => !value);
    const current = next < 0 ? 3 : next;
    for (const [index, name] of ['project', 'provider', 'telegram', 'run'].entries()) {
      $('setup-' + name).open = index === current;
    }
  }
  setupReady = ready;
}

async function request(path, value) {
  if (nativeDesktop) {
    try {
      return await window.__TAURI__.core.invoke('relay_request', {path, value: value ?? {}});
    } catch (error) {
      throw new Error(typeof error === 'string' ? error : 'Action could not finish.');
    }
  }
  const response = await fetch(root + 'api/' + path, value === undefined ? undefined : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Action could not finish.');
  return result;
}

async function refresh() {
  try {
    if (nativeDesktop) {
      $('desktop-retry').hidden = true;
      $('desktop-feedback').textContent = 'Reading local status…';
      $('desktop-feedback').hidden = false;
    }
    const info = await request('status');
    if (nativeDesktop) $('desktop-feedback').hidden = true;
    $('install-guide').hidden = true;
    $('install-overview').hidden = true;
    $('install-note').hidden = true;
    $('live-overview').hidden = false;
    $('live-setup').hidden = false;
    if (nativeDesktop) {
      $('setup').hidden = false;
      document.querySelector('.steps').hidden = false;
    }
    $('mode-label').textContent = nativeDesktop ? 'Desktop setup' : 'Local setup';
    $('hero-lead').textContent = 'Task Relay connects a project, your chosen AI provider, and a Telegram inbox. Complete setup here, then bring the first task into focus.';
    $('version').textContent = 'Version ' + info.version;
    $('platform').textContent = info.platform === 'darwin' ? 'macOS' : info.platform;
    const supported = info.platform === 'darwin' || info.platform === 'linux';
    document.querySelectorAll('form button[type=submit]').forEach(button => { button.disabled = !supported; });
    if (!supported) feedback('project-feedback', 'Setup controls are not supported on this host yet. Local status remains available.', true);
    const project = info.project;
    $('project-summary').textContent = project.available ? project.name : project.path ? 'Saved folder unavailable' : nativeDesktop ? 'Optional default folder' : 'Choose a folder';
    $('current-project').textContent = project.path ? project.path + (project.available ? '' : ' — unavailable') : nativeDesktop ? 'No default folder selected. Choose one when a task needs existing files.' : 'No project selected yet.';
    if (nativeDesktop && project.available && !$('task-create-project').dataset.touched) $('task-create-project').value = project.path;
    state('project', project.available);
    if (nativeDesktop && !project.available) {
      $('project-pill').textContent = 'Optional';
      $('project-pill').classList.remove('waiting');
      $('project-state').textContent = '—';
    }
    const connected = Object.entries(info.providers).filter(([, ready]) => ready).map(([name]) => name);
    $('provider-summary').textContent = connected.length ? connected.join(', ') : info.selected_provider === 'later' ? 'Using existing tasks' : 'Choose a provider';
    state('provider', connected.length > 0 || info.selected_provider === 'later');
    if (info.selected_provider && $('provider-name').dataset.touched !== 'true') $('provider-name').value = info.selected_provider;
    if (nativeDesktop && info.selected_provider && info.selected_provider !== 'later' && !$('task-create-provider').dataset.touched) $('task-create-provider').value = info.selected_provider;
    updateProviderFields();
    $('telegram-summary').textContent = info.telegram.paired ? 'Paired locally' : info.telegram.configured ? 'Bot saved · pairing pending' : 'Connect a bot';
    state('telegram', info.telegram.configured);
    $('telegram-pill').textContent = info.telegram.paired ? 'Paired' : info.telegram.configured ? 'Pairing pending' : 'To do';
    syncSetupSteps([nativeDesktop || project.available, connected.length > 0 || info.selected_provider === 'later', info.telegram.configured]);
    $('first-task-row').hidden = nativeDesktop || !info.first_task_command;
    $('first-task-hint').hidden = nativeDesktop || !!info.first_task_command;
    if (info.first_task_command) {
      $('first-task-command').textContent = info.first_task_command;
      $('first-task-copy').dataset.copy = info.first_task_command;
    }
    const doctor = $('doctor-list');
    doctor.replaceChildren(...info.doctor.checks.map(c => checkItem(c.check, c.status, c.detail)));
    if (info.setup_error) doctor.prepend(checkItem('Saved setup', 'fail', info.setup_error));
    const tools = $('tool-list');
    tools.replaceChildren(...info.tools.map(t => checkItem(t.name, t.available ? 'ok' : 'warn', t.detail)));
    $('update-title').textContent = info.update.latest ? 'Latest cached: ' + info.update.latest : 'No release cached';
    $('update-detail').textContent = info.update.error || (info.update.checked ? 'Last checked on this computer' : 'Check GitHub for a stable release');
    if (nativeDesktop) {
      const snapshot = await refreshDesktop();
      const hasTasks = snapshot.tasks.length > 0;
      $('setup-start-link').hidden = hasTasks;
      $('desktop-tasks-link').hidden = !hasTasks;
      $('setup-start-link').textContent = connected.length || info.telegram.configured ? 'Continue setup ↓' : 'Start setup ↓';
      $('hero-title').textContent = hasTasks ? 'Your setup, in one place.' : 'Get Task Relay ready.';
      $('hero-lead').textContent = hasTasks
        ? 'Review your provider, Telegram connection and optional default folder here. Your saved work is in Jobs.'
        : 'Connect a provider and Telegram bot, then start Relay. Add a default folder only if you want one.';
      if (autoTabPending) {
        showTab(hasTasks ? 'tasks' : 'setup');
        autoTabPending = false;
      }
    }
  } catch (error) {
    if (nativeDesktop) {
      feedback('desktop-feedback', 'Could not read local setup: ' + error.message, true);
      $('desktop-feedback').hidden = false;
      $('desktop-retry').hidden = false;
      $('plan-create-button').disabled = true;
      feedback('plan-feedback', 'Relay data is unavailable: ' + error.message, true);
      return;
    }
    if ($('live-setup').hidden) {
      $('launch-feedback').textContent = 'Local status is unavailable. Open Setup.command from the extracted folder to install Relay and launch the live setup page.';
    } else {
      feedback('update-feedback', 'Local status is unavailable. Try task-relay doctor.', true);
    }
  }
}

if (nativeDesktop) {
  $('desktop-retry').addEventListener('click', refresh);
  document.body.classList.add('desktop-app');
  $('app-tabs').hidden = false;
  $('app-tabs').setAttribute('aria-orientation', 'vertical');
  $('app-usage-panel').append(document.querySelector('.usage-panel'));
  $('app-workflows-panel').append($('new-workflow'));
  $('app-tools-panel').append(document.querySelector('#app-tools-panel > .panel'));
  const rail = document.createElement('aside');
  rail.id = 'jobs-sidebar';
  rail.append(document.querySelector('#task-grid > .panel'));
  const inboxLabel = document.createElement('p'); inboxLabel.id = 'approval-inbox-label';
  const inbox = document.createElement('div'); inbox.id = 'approval-inbox';
  rail.prepend(inboxLabel, inbox);
  refreshApprovalInbox();
  setInterval(() => { if (!document.hidden) refreshApprovalInbox(); }, 15000);
  document.querySelector('.shell').append(rail);
  $('workflow-kind').addEventListener('change', () => refreshWorkflowLibrary());
  $('workflow-refresh').addEventListener('click', () => refreshWorkflowLibrary());
  $('workflow-more').addEventListener('click', () => refreshWorkflowLibrary(true));
  $('tools-refresh').addEventListener('click', refreshTools);
  $('job-search').addEventListener('input', renderJobs);
  $('reels-draft').addEventListener('click', () => {
    showTab('workflows', true);
    $('new-workflow').open = true;
    $('plan-goal').value = 'Assess one repeated step in my reels project for a reusable automation. Identify the existing script or manual process, exact inputs and outputs, failure cases, and a small text-fixture validation plan. Ask for missing project evidence.';
    $('plan-constraints').value = 'Assessment only. Do not generate media, render, publish, schedule, install or execute the proposed automation.';
    $('plan-goal').focus();
  });
  $('app-setup-panel').append(document.querySelector('.hero'), $('setup'), document.querySelector('.steps'));
  $('app-system-panel').append(document.querySelector('.service-panel'), document.querySelector('.bottom-grid'));
  $('app-tasks-panel').append($('desktop-workspace'));
  $('task-history').insertBefore($('task-approvals'), $('task-events'));
  $('setup').hidden = true;
  document.querySelector('.steps').hidden = true;
  showTab('setup');
  $('app-tabs').addEventListener('click', event => {
    const button = event.target instanceof Element ? event.target.closest('[data-tab]') : null;
    if (button) showTab(button.dataset.tab, true);
  });
  $('app-tabs').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    const order = appSections;
    const next = order[(order.indexOf(activeTab) + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : order.length - 1)) % order.length];
    showTab(next, true);
    $('tab-' + next).focus();
    event.preventDefault();
  });
  $('desktop-tasks-link').addEventListener('click', event => {
    event.preventDefault();
    showTab('tasks', true);
  });
  $('setup-start-link').addEventListener('click', () => {
    const current = document.querySelector('.steps .step[open]') || $('setup-project');
    current.open = true;
    current.scrollIntoView({behavior: 'smooth', block: 'start'});
  });
  $('setup-system-link').addEventListener('click', () => showTab('system', true));
  for (const id of ['install-guide', 'install-overview', 'install-note', 'source-download', 'source-download-note', 'service-command']) $(id).hidden = true;
  $('desktop-feedback').hidden = false;
  $('desktop-feedback').textContent = 'Connecting to the bundled setup…';
  $('mode-label').textContent = 'Desktop setup';
  $('hero-lead').textContent = 'Connect a provider and set up your Telegram bot. Choose working folders when tasks need them.';
  $('step-project-title').textContent = 'Default folder (optional)';
  document.querySelector('#setup-project .step-header small').textContent = 'Pre-fill new tasks with one folder, or choose folders later.';
  document.querySelector('#setup-project .step-body > .fine').textContent = 'This only saves a starting folder. It does not grant Relay or a worker access to the whole computer.';
  $('step-run-description').textContent = 'Open System to start Relay, pair in Telegram, then verify a real reply.';
  $('service-help').textContent = 'The app starts and stops only its own service. Starting it does not send a task; sending an instruction may use a paid provider.';
  $('footer-copy').textContent = 'Task Relay setup runs locally. Your credentials, task history and project files stay on this computer.';
  $('project-browse').hidden = false;
  $('desktop-workspace').hidden = false;
  $('setup-system-link').hidden = false;
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Unknown';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return (unit ? value.toFixed(unit >= 3 || value < 10 ? 1 : 0) : String(value)) + ' ' + units[unit];
}

async function refreshUsage() {
  $('usage-refresh').disabled = true;
  try {
    const result = await request('usage-summary');
    const tokens = result.tokens;
    const storage = result.storage;
    const source = result.source_folder;
    const displayedStorage = source || storage;
    $('usage-tokens').textContent = tokens.relay_total === null ? 'Not measured' : tokens.relay_total.toLocaleString();
    $('usage-token-detail').textContent = tokens.relay_records
      ? 'Direct API tasks ' + (tokens.relay_api_total === null ? 'unmeasured' : tokens.relay_api_total.toLocaleString()) +
        ' · ' + tokens.relay_records.toLocaleString() + ' Relay records' +
        (tokens.relay_unmeasured ? ' · ' + tokens.relay_unmeasured.toLocaleString() + ' unmeasured' : '')
      : 'No recorded Relay calls in this period';
    $('usage-all-tokens').textContent = tokens.total === null ? 'Not measured' : tokens.total.toLocaleString();
    $('usage-all-detail').textContent = 'Input ' + (tokens.input === null ? 'unknown' : tokens.input.toLocaleString()) +
      ' · output ' + (tokens.output === null ? 'unknown' : tokens.output.toLocaleString()) +
      (tokens.unmeasured ? ' · ' + tokens.unmeasured.toLocaleString() + ' unmeasured' : '');
    $('usage-storage-label').textContent = source ? 'Task Relay source folder' : 'Relay storage';
    $('usage-storage').textContent = (displayedStorage.complete ? '' : '≥ ') + formatBytes(displayedStorage.bytes);
    $('usage-storage-detail').textContent = (source ? 'Relay storage ' + (storage.complete ? '' : '≥ ') + formatBytes(storage.bytes) + ' included · ' : '') + storage.folders.map(folder =>
      folder.name + ' ' + (folder.complete ? '' : '≥ ') + formatBytes(folder.bytes)).join(' · ');
    $('usage-note').textContent = tokens.status + (tokens.oldest_source_check
      ? ' Oldest source check: ' + new Date(tokens.oldest_source_check * 1000).toLocaleString() + '.'
      : tokens.indexing_enabled ? ' Background indexing is enabled.' : ' Background indexing is off or not yet available.') +
      (source ? ' Source-folder size includes this checkout, builds and its saved data; it excludes the separate installed app.'
        : ' Storage includes data, workspaces and generated files at the current binding; it excludes the app bundle and unrelated project folders.') +
      (storage.complete && (!source || source.complete) ? '' : ' An incomplete scan is shown as a lower bound.');
  } catch (error) {
    $('usage-tokens').textContent = 'Unavailable';
    $('usage-all-tokens').textContent = 'Unavailable';
    $('usage-storage').textContent = 'Unavailable';
    $('usage-note').textContent = 'Could not read usage at this data location: ' + error.message;
  } finally {
    $('usage-refresh').disabled = false;
  }
}

function storageRows(items, target) {
  target.replaceChildren(...items.map(item => {
    const row = document.createElement('div'); row.className = 'storage-row';
    const name = document.createElement('span'); name.textContent = item.name;
    const size = document.createElement('strong'); size.textContent = formatBytes(item.bytes);
    row.append(name, size); return row;
  }));
}

async function refreshStorageBreakdown() {
  const target = $('storage-categories');
  target.textContent = 'Reading local folders…';
  try {
    const result = await request('storage-breakdown');
    storageRows(result.categories, target);
    if (!result.complete) target.append(checkItem('Partial scan', 'warn', 'Folder sizes are lower bounds. Refresh to try again.'));
  } catch (error) {
    target.textContent = 'Could not inspect folders: ' + error.message;
  }
}

async function previewCleanup() {
  cleanupManifest = null;
  $('cleanup-review').hidden = true;
  $('cleanup-preview').disabled = true;
  feedback('cleanup-feedback', 'Checking disposable files…');
  try {
    const result = await request('cleanup-preview');
    cleanupManifest = result.manifest;
    $('cleanup-review').hidden = false;
    $('cleanup-summary').textContent = result.files.toLocaleString() + ' verified files · ' + formatBytes(result.bytes) + ' eligible to clear.';
    storageRows(Object.entries(result.kinds).map(([name, value]) => ({name: name.replaceAll('-', ' ') + ' · ' + value.files.toLocaleString() + ' files', bytes: value.bytes})), $('cleanup-kinds'));
    $('cleanup-apply').disabled = result.files === 0;
    feedback('cleanup-feedback', result.files ? 'Review the categories, then choose whether to delete only these files.' : 'No disposable files were found.');
  } catch (error) { feedback('cleanup-feedback', error.message, true); }
  finally { $('cleanup-preview').disabled = false; }
}

async function applyCleanup() {
  if (!cleanupManifest) return;
  $('cleanup-apply').disabled = true;
  feedback('cleanup-feedback', 'Checking identities and removing the selected files…');
  try {
    const result = await request('cleanup-apply', {manifest: cleanupManifest});
    cleanupManifest = null;
    $('cleanup-review').hidden = true;
    feedback('cleanup-feedback', 'Removed ' + result.removed.toLocaleString() + ' files (' + formatBytes(result.bytes) + '); ' + result.skipped.toLocaleString() + ' changed or unavailable files skipped.');
    await refreshUsage();
    await refreshStorageBreakdown();
  } catch (error) { feedback('cleanup-feedback', error.message, true); }
}

async function refreshDesktop() {
  const service = await request('service-status');
  $('service-status-text').textContent = service.detail;
  $('service-location').textContent = service.healthy ? 'A recent Telegram poll was observed. Provider work and reply delivery require a real check.' : 'No fresh Telegram poll has been verified for this data location.';
  $('service-start').hidden = service.owner === 'other' || service.healthy || service.bound_source;
  $('service-stop').hidden = service.owner !== 'desktop' || !service.loaded;
  $('service-connect').hidden = !service.connectable || service.bound_source;
  $('service-disconnect').hidden = !service.bound_source;
  const result = await request('tasks');
  await refreshApprovalInbox();
  await refreshPlans();
  $('tasks-location').textContent = 'Task history: ' + result.data;
  taskCanCreate = result.can_create;
  $('task-create-button').disabled = !taskCanCreate;
  const lastCreation = result.creations[0];
  $('task-create-last').textContent = lastCreation ? 'Last creation: ' + lastCreation.status + ' · ' + lastCreation.request_id + (lastCreation.task_id ? ' · task ' + lastCreation.task_id : '') + (lastCreation.result ? ' · ' + lastCreation.result : '') : '';
  const creation = pendingCreation && result.creations.find(row => row.request_id === pendingCreation.id);
  if (creation) {
    feedback('task-create-feedback', creation.result || 'Task creation ' + creation.status + '.', creation.status === 'rejected');
    if (creation.status === 'accepted' && creation.task_id) {
      selectedTask = creation.task_id;
      pendingCreation = null;
      $('new-task').open = false;
      $('task-create-title').value = '';
    } else if (creation.status === 'rejected') {
      pendingCreation = null;
    }
  } else if (!taskCanCreate && !pendingCreation) {
    feedback('task-create-feedback', 'A current Relay service is needed to create tasks here. Complete Setup or check System.');
  }
  const list = $('tasks-list');
  if (!result.tasks.length) {
    savedJobs = [];
    $('task-panel').hidden = true;
    $('task-grid').classList.add('single');
    list.replaceChildren(checkItem('No saved tasks here', 'warn', service.connectable ? 'Open System to connect this app to the existing service’s history.' : taskCanCreate ? 'Use New task above to create one.' : 'Finish Setup or check System, then refresh.'));
    selectedTask = null;
    taskCanSend = false;
    $('task-title').textContent = 'Choose a task';
    $('task-current').hidden = true;
    $('task-latest').textContent = '';
    $('task-send-form').hidden = true;
    $('task-events').replaceChildren();
    $('task-commands').replaceChildren();
    return result;
  }
  $('task-panel').hidden = false;
  $('task-grid').classList.remove('single');
  savedJobs = result.tasks;
  renderJobs();
  if (!result.tasks.some(task => task.id === selectedTask)) selectedTask = result.tasks[0].id;
  await showTask(selectedTask);
  return result;
}

async function refreshPlans() {
  const result = await request('plans');
  if (pendingPlan?.plan_id && result.plans.some(plan => plan.id === pendingPlan.plan_id)) {
    selectedPlan = pendingPlan.plan_id;
    pendingPlan = null;
    planParentId = null;
    $('plan-cancel-revision').hidden = true;
  }
  planCanCreate = result.can_plan;
  $('plan-create-button').disabled = !planCanCreate;
  const list = $('plans-list');
  list.replaceChildren(...result.plans.map(plan => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'task-row' + (plan.id && plan.id === selectedPlan ? ' selected' : '');
    button.dataset.planId = plan.id || '';
    button.disabled = !plan.id;
    const title = document.createElement('strong');
    title.textContent = plan.prompt.split('\n')[0].slice(0, 130);
    const status = document.createElement('small');
    status.textContent = [plan.status || plan.request_status, plan.project || 'Isolated workspace', plan.result && plan.request_status === 'rejected' ? plan.result : ''].filter(Boolean).join(' · ');
    button.append(title, status);
    return button;
  }));
  if (!result.plans.length) list.append(checkItem('No workflow drafts yet', 'warn', 'Describe a bounded outcome above to generate one.'));
  if (!planCanCreate) feedback('plan-feedback', 'A current Relay service is needed for planning. Complete Setup or check System.');
  if (!selectedPlan || !result.plans.some(plan => plan.id === selectedPlan)) selectedPlan = result.plans.find(plan => plan.id)?.id || null;
  if (selectedPlan) await showPlan(selectedPlan);
  else $('plan-detail').hidden = true;
}

async function showPlan(ident) {
  selectedPlan = ident;
  const detail = await request('plan-detail', {plan_id: ident});
  activePlan = detail;
  document.querySelectorAll('#plans-list .task-row').forEach(button => button.classList.toggle('selected', button.dataset.planId === ident));
  $('plan-detail').hidden = false;
  $('plan-title').textContent = detail.request.split('\n')[0].slice(0, 140);
  $('plan-status').textContent = [detail.id, detail.status, detail.run ? 'Run: ' + detail.run : 'No workers started', detail.error].filter(Boolean).join(' · ');
  renderMarkdown($('plan-preview'), detail.preview || (detail.error || 'Planning ' + detail.status + '. Refresh to see the result.'));
  const documents = $('plan-documents');
  documents.replaceChildren(...detail.documents.map(doc => {
    const panel = document.createElement('details');
    panel.className = 'plan-document';
    const summary = document.createElement('summary');
    summary.textContent = doc.filename + ' · SHA-256 ' + doc.sha256.slice(0, 12);
    const caption = document.createElement('small');
    caption.textContent = doc.caption || 'Exact review document';
    const content = document.createElement('pre');
    content.textContent = doc.content;
    panel.append(summary, caption);
    if (/\.md$/i.test(doc.filename)) {
      const rendered = document.createElement('div'); renderMarkdown(rendered, doc.content);
      const raw = document.createElement('details'); const rawTitle = document.createElement('summary'); rawTitle.textContent = 'Exact Markdown source';
      raw.append(rawTitle, content); panel.append(rendered, raw);
    } else panel.append(content);
    const key = doc.id + ':' + doc.sha256;
    panel.addEventListener('toggle', () => {
      if (panel.open) { openedPlanDocuments.add(key); updatePlanButtons(); }
    });
    return panel;
  }));
  updatePlanButtons();
}

function updatePlanButtons() {
  const plan = activePlan;
  if (!plan) return;
  const ready = plan.status === 'ready';
  const documentsOpened = !plan.review_error && plan.documents.every(doc => openedPlanDocuments.has(doc.id + ':' + doc.sha256));
  $('plan-prepare').hidden = !ready || !plan.planning_only;
  $('plan-revise').hidden = !['ready', 'needs_input', 'blocked'].includes(plan.status);
  $('plan-start').hidden = !ready || plan.planning_only;
  $('plan-start').disabled = !documentsOpened;
  $('plan-discard').hidden = !ready;
  $('plan-discard').disabled = !documentsOpened;
  $('plan-review-hint').textContent = plan.review_error || (ready ? (documentsOpened
    ? 'This approval is for the exact proposal shown here. Progress and output choices continue in paired Telegram; no later stage is authorized.'
    : 'Open each attached document to review its exact contents before Start or Discard. Starting requires paired Telegram for later decisions.') :
    'A draft is not execution authorization. Refresh when planning finishes.');
}

async function showTask(taskId) {
  if (selectedTask && selectedTask !== taskId) clearSelectedFile();
  selectedTask = taskId;
  taskCanSend = false;
  $('task-send-button').disabled = true;
  document.querySelectorAll('.task-row').forEach(button => button.classList.toggle('selected', button.dataset.taskId === taskId));
  const detail = await request('task-detail', {task_id: taskId});
  if (selectedTask !== taskId) return;
  $('approval-status').textContent = detail.approvals.length ? detail.approvals.length + ' pending decision(s) — review below' : 'No pending approval recorded for this job. Refresh to check again.';
  $('task-title').textContent = detail.task.title || taskId;
  $('task-meta').textContent = [detail.task.backend, detail.task.project].filter(Boolean).join(' · ');
  const job = detail.jobs[0];
  $('task-current').hidden = false;
  $('task-current-status').textContent = detail.task.status === 'idle' ? 'Ready' : detail.task.status;
  $('task-current-detail').textContent = job ? 'Latest managed run: ' + job.status + (job.cancel ? ' · stop requested' : '') : 'No managed run recorded';
  const approvals = $('task-approvals');
  approvals.hidden = !detail.approvals.length;
  approvals.replaceChildren(...detail.approvals.map(card => {
    const item = document.createElement('article');
    item.className = 'approval-card';
    const heading = document.createElement('strong');
    heading.textContent = card.title + ' · needs your decision';
    const review = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'Review exact request';
    const body = document.createElement('pre');
    body.textContent = card.review;
    review.append(summary, body);
    const actions = document.createElement('div');
    actions.className = 'task-actions';
    if (card.can_allow) {
      const allow = document.createElement('button');
      allow.type = 'button'; allow.className = 'button button-dark'; allow.textContent = 'Allow once';
      allow.dataset.approvalAction = 'allow'; allow.disabled = true;
      actions.append(allow);
    }
    if (card.can_deny) {
      const deny = document.createElement('button');
      deny.type = 'button'; deny.className = 'button button-secondary'; deny.textContent = 'Deny';
      deny.dataset.approvalAction = 'deny'; actions.append(deny);
    }
    if (card.can_answer) {
      const answer = document.createElement('textarea');
      answer.placeholder = 'Answer the question shown above'; answer.maxLength = 4000;
      answer.setAttribute('aria-label', 'Answer this Codex question');
      const send = document.createElement('button');
      send.type = 'button'; send.className = 'button button-dark'; send.textContent = 'Send answer';
      send.dataset.approvalAction = 'answer'; send.disabled = true;
      answer.addEventListener('input', () => { send.disabled = !review.open || !answer.value.trim(); });
      review.addEventListener('toggle', () => { send.disabled = !review.open || !answer.value.trim(); });
      review.append(answer); actions.append(send);
    }
    review.addEventListener('toggle', () => {
      const allow = actions.querySelector('[data-approval-action="allow"]');
      if (allow) allow.disabled = !review.open;
    });
    item.dataset.token = card.token;
    item.dataset.fingerprint = card.fingerprint;
    item.append(heading, review, actions);
    return item;
  }));
  const events = (detail.messages || detail.events).map(event => {
    const item = document.createElement('div');
    item.className = 'task-event' + (event.role === 'user' ? ' user-message' : '');
    const label = document.createElement('strong');
    label.textContent = event.role === 'user' ? 'You' + (event.status ? ' · ' + event.status : '') : event.channel === 'codex' ? 'Codex' : event.channel === 'desktop' ? 'Desktop activity' : 'Relay activity';
    const body = document.createElement('div');
    renderMarkdown(body, event.text);
    item.append(label, body);
    return item;
  });
  $('task-events').replaceChildren(...events);
  if (!events.length) $('task-events').append(checkItem('No recent activity', 'warn', 'Task status will appear after Relay records an event.'));
  $('task-history').querySelector('summary').textContent = 'Conversation · ' + events.length + ' recent messages';
  $('history-note').textContent = detail.history_note || '';
  const latest = detail.events.at(-1);
  $('task-latest').textContent = latest ? 'Latest: ' + latest.text.slice(0, 320) + (latest.text.length > 320 ? '…' : '') : 'No recent activity.';
  $('task-commands').replaceChildren(...detail.commands.map(command => {
    const item = document.createElement('div');
    item.className = 'task-event';
    const label = document.createElement('strong');
    label.textContent = command.status + ' · ' + command.request_id;
    const body = document.createElement('p');
    body.textContent = command.result || 'Recorded; awaiting service receipt.';
    item.append(label, body);
    return item;
  }));
  $('task-receipts').hidden = detail.commands.length === 0;
  $('task-receipts').querySelector('summary').textContent = 'Submission receipts (' + detail.commands.length + ')';
  $('task-send-form').hidden = false;
  taskCanSend = detail.can_send;
  $('task-send-button').disabled = !taskCanSend;
  $('task-file-browse').disabled = !taskCanSend;
  $('task-stop-button').hidden = !detail.can_stop;
  if (!detail.can_send) feedback('task-feedback', detail.task.status !== 'idle'
    ? 'This task is ' + detail.task.status + '. Wait until it is ready before sending another instruction.'
    : 'The service has not advertised current desktop command support. You can still view this task; update and restart that service to send here.');
  else if (!pendingInstruction) feedback('task-feedback', '');
  const last = detail.commands[0];
  if (last && !pendingInstruction && ['uncertain', 'rejected'].includes(last.status)) feedback('task-feedback', 'Last desktop instruction: ' + last.status + '. ' + (last.result || ''), true);
}

function clearSelectedFile() {
  selectedFile = null;
  $('task-file-name').textContent = '';
  $('task-file-clear').hidden = true;
}

if (nativeDesktop) {
  $('plan-project').addEventListener('input', () => { $('plan-project').dataset.touched = 'true'; });
  $('plan-browse').addEventListener('click', async () => {
    try {
      const selected = await window.__TAURI__.dialog.open({directory: true, multiple: false, canCreateDirectories: false});
      if (typeof selected === 'string') {
        $('plan-project').value = selected;
        $('plan-project').dataset.touched = 'true';
      }
    } catch (_) { feedback('plan-feedback', 'The folder picker could not open. Enter an absolute folder path.', true); }
  });
  $('plan-create-form').addEventListener('submit', async event => {
    event.preventDefault();
    const goal = $('plan-goal').value.trim();
    const constraints = $('plan-constraints').value.trim();
    const project = $('plan-project').value.trim() || null;
    if (!planCanCreate || !goal) return;
    if (!pendingPlan || pendingPlan.goal !== goal || pendingPlan.constraints !== constraints || pendingPlan.project !== project || pendingPlan.parent_id !== planParentId) {
      pendingPlan = {goal, constraints, project, parent_id: planParentId, request_id: crypto.randomUUID()};
    }
    $('plan-create-button').disabled = true;
    feedback('plan-feedback', 'Saving planning request…');
    try {
      const receipt = await request('plan-create', pendingPlan);
      pendingPlan.plan_id = receipt.plan_id;
      selectedPlan = receipt.plan_id;
      feedback('plan-feedback', receipt.message, receipt.status === 'rejected');
      await refreshPlans();
      if (receipt.status === 'queued') setTimeout(() => refreshPlans().catch(error => feedback('plan-feedback', error.message, true)), 6000);
      if (receipt.status === 'accepted') { pendingPlan = null; planParentId = null; $('plan-cancel-revision').hidden = true; }
    } catch (error) {
      feedback('plan-feedback', error.message + ' The same request identity will be used if you retry unchanged content.', true);
    } finally { $('plan-create-button').disabled = !planCanCreate; }
  });
  $('plans-list').addEventListener('click', event => {
    const button = event.target instanceof Element ? event.target.closest('[data-plan-id]') : null;
    if (button?.dataset.planId) {
      if (planParentId && planParentId !== button.dataset.planId) {
        planParentId = null;
        pendingPlan = null;
        $('plan-cancel-revision').hidden = true;
      }
      showPlan(button.dataset.planId).catch(error => feedback('plan-feedback', error.message, true));
    }
  });
  $('plans-refresh').addEventListener('click', () => refreshPlans().catch(error => feedback('plan-feedback', error.message, true)));
  $('plan-cancel-revision').addEventListener('click', () => {
    planParentId = null;
    pendingPlan = null;
    $('plan-cancel-revision').hidden = true;
    feedback('plan-feedback', 'New workflow draft.');
  });
  $('plan-revise').addEventListener('click', () => {
    if (!activePlan) return;
    planParentId = activePlan.id;
    $('plan-cancel-revision').hidden = false;
    pendingPlan = null;
    $('plan-goal').value = '';
    $('plan-constraints').value = '';
    $('plan-project').value = activePlan.project || '';
    $('new-workflow').open = true;
    $('plan-goal').focus();
    feedback('plan-feedback', 'Revising ' + planParentId + '. Describe only the correction or missing input; the original request is retained.');
  });
  $('plan-prepare').addEventListener('click', async () => {
    if (!selectedPlan) return;
    $('plan-prepare').disabled = true;
    try {
      await request('plan-prepare', {plan_id: selectedPlan});
      await showPlan(selectedPlan);
      feedback('plan-feedback', 'Exact plan ready for review. No workers started.');
    } catch (error) { feedback('plan-feedback', error.message, true); }
    finally { $('plan-prepare').disabled = false; }
  });
  for (const [id, verb] of [['plan-start', 'start'], ['plan-discard', 'discard']]) {
    $(id).addEventListener('click', async () => {
      if (!activePlan?.review_digest) return;
      $(id).disabled = true;
      try {
        const result = await request('plan-decide', {plan_id: activePlan.id, verb, review_digest: activePlan.review_digest});
        feedback('plan-feedback', result.message);
        await refreshPlans();
      } catch (error) { feedback('plan-feedback', error.message, true); }
      finally { updatePlanButtons(); }
    });
  }
  $('task-file-browse').addEventListener('click', async () => {
    try {
      const selected = await window.__TAURI__.dialog.open({multiple: false, filters: [{name: 'Text files', extensions: ['txt', 'md']}]});
      if (typeof selected === 'string') {
        selectedFile = selected;
        $('task-file-name').textContent = selected.split(/[\\/]/).pop();
        $('task-file-clear').hidden = false;
      }
    } catch (_) {
      feedback('task-feedback', 'The file picker could not open. Try again.', true);
    }
  });
  $('task-file-clear').addEventListener('click', () => { clearSelectedFile(); pendingInstruction = null; });
  $('task-approvals').addEventListener('click', async event => {
    const button = event.target instanceof Element ? event.target.closest('[data-approval-action]') : null;
    if (!button || button.disabled) return;
    const card = button.closest('.approval-card');
    const taskId = selectedTask;
    const action = button.dataset.approvalAction;
    const answer = action === 'answer' ? card.querySelector('textarea')?.value.trim() : null;
    if (action === 'answer' && !answer) return;
    card.querySelectorAll('button').forEach(control => { control.disabled = true; });
    try {
      const result = await request('task-approval-decide', {
        task_id: taskId, token: card.dataset.token, fingerprint: card.dataset.fingerprint,
        allow: action === 'allow', answer
      });
      feedback('task-feedback', result.message);
      await showTask(taskId);
    } catch (error) {
      feedback('task-feedback', error.message, true);
      await showTask(taskId);
    }
  });
  $('task-create-project').addEventListener('input', () => { $('task-create-project').dataset.touched = 'true'; });
  $('task-create-provider').addEventListener('change', () => { $('task-create-provider').dataset.touched = 'true'; });
  $('task-create-browse').addEventListener('click', async () => {
    try {
      const selected = await window.__TAURI__.dialog.open({directory: true, multiple: false, canCreateDirectories: false});
      if (typeof selected === 'string') {
        $('task-create-project').value = selected;
        $('task-create-project').dataset.touched = 'true';
      }
    } catch (_) {
      feedback('task-create-feedback', 'The folder picker could not open. Enter an absolute project path.', true);
    }
  });
  $('task-create-form').addEventListener('submit', async event => {
    event.preventDefault();
    const backend = $('task-create-provider').value;
    const project = $('task-create-project').value.trim();
    const title = $('task-create-title').value.trim();
    if (!taskCanCreate) return;
    if (!pendingCreation || pendingCreation.backend !== backend || pendingCreation.project !== project || pendingCreation.title !== title) {
      pendingCreation = {backend, project, title, id: crypto.randomUUID()};
    }
    $('task-create-button').disabled = true;
    feedback('task-create-feedback', 'Recording task creation…');
    try {
      const result = await request('task-create', {backend, project, title, request_id: pendingCreation.id});
      feedback('task-create-feedback', result.message, result.status === 'rejected');
      await refreshDesktop();
      if (result.status === 'queued') setTimeout(() => refreshDesktop().catch(error => feedback('task-create-feedback', error.message, true)), 6000);
    } catch (error) {
      feedback('task-create-feedback', error.message + ' The unchanged request keeps its identity if retried.', true);
    } finally {
      $('task-create-button').disabled = !taskCanCreate;
    }
  });
  for (const [id, action] of [['service-start', 'service-start'], ['service-stop', 'service-stop'], ['service-connect', 'service-connect'], ['service-disconnect', 'service-disconnect']]) {
    $(id).addEventListener('click', async () => {
      $(id).disabled = true;
      feedback('service-feedback', 'Working…');
      try {
        const result = await request(action, {});
        feedback('service-feedback', result.message);
        await refresh();
        await refreshUsage();
      } catch (error) {
        feedback('service-feedback', error.message, true);
      } finally {
        $(id).disabled = false;
      }
    });
  }
  $('tasks-refresh').addEventListener('click', () => {
    refreshDesktop().catch(error => feedback('task-feedback', error.message, true));
  });
  $('usage-refresh').addEventListener('click', refreshUsage);
  $('storage-details').addEventListener('toggle', () => { if ($('storage-details').open) refreshStorageBreakdown(); });
  $('cleanup-preview').addEventListener('click', previewCleanup);
  $('cleanup-apply').addEventListener('click', applyCleanup);
  $('tasks-list').addEventListener('click', event => {
    const button = event.target instanceof Element ? event.target.closest('.task-row') : null;
    if (button) { showTab('tasks', true); $('task-panel').hidden = false; }
    if (button) showTask(button.dataset.taskId).catch(error => feedback('task-feedback', error.message, true));
  });
  $('task-send-form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = $('task-instruction').value.trim();
    if (!selectedTask || (!text && !selectedFile)) return;
    if (!pendingInstruction || pendingInstruction.taskId !== selectedTask || pendingInstruction.text !== text || pendingInstruction.file !== selectedFile) {
      pendingInstruction = {taskId: selectedTask, text, file: selectedFile, id: crypto.randomUUID()};
    }
    $('task-send-button').disabled = true;
    feedback('task-feedback', 'Recording instruction…');
    try {
      const result = selectedFile
        ? await request('task-send-file', {task_id: selectedTask, path: selectedFile, text, request_id: pendingInstruction.id})
        : await request('task-send', {task_id: selectedTask, text, request_id: pendingInstruction.id});
      feedback('task-feedback', result.message);
      if (result.status === 'queued' || result.status === 'accepted') {
        pendingInstruction = null;
        $('task-instruction').value = '';
        clearSelectedFile();
      }
      await showTask(selectedTask);
    } catch (error) {
      feedback('task-feedback', error.message + ' The same request identity will be used if you retry this unchanged text.', true);
    } finally {
      $('task-send-button').disabled = !taskCanSend;
    }
  });
  $('task-stop-button').addEventListener('click', async () => {
    if (!selectedTask) return;
    $('task-stop-button').disabled = true;
    try {
      const result = await request('task-stop', {task_id: selectedTask});
      feedback('task-feedback', result.message);
      await showTask(selectedTask);
    } catch (error) {
      feedback('task-feedback', error.message, true);
    } finally {
      $('task-stop-button').disabled = false;
    }
  });
}

$('project-browse').addEventListener('click', async () => {
  try {
    const selected = await window.__TAURI__.dialog.open({directory: true, multiple: false, canCreateDirectories: false});
    if (typeof selected === 'string') $('project-path').value = selected;
  } catch (_) {
    feedback('project-feedback', 'The folder picker could not open. You can enter an absolute folder path.', true);
  }
});

if (nativeDesktop) document.addEventListener('click', async event => {
  const link = event.target instanceof Element ? event.target.closest('a[href^="https://"]') : null;
  if (!link) return;
  event.preventDefault();
  try {
    await window.__TAURI__.opener.openUrl(link.href);
  } catch (_) {
    feedback('desktop-feedback', 'Could not open that link in your browser.', true);
    $('desktop-feedback').hidden = false;
  }
});

function updateProviderFields() {
  const name = $('provider-name').value;
  $('key-field').hidden = name === 'later';
  $('model-field').hidden = name === 'later';
  $('endpoint-field').hidden = name !== 'qwen';
  $('provider-key-link').hidden = name === 'later';
  if (urls[name]) $('provider-key-link').href = urls[name];
}

async function submit(form, path, value, feedbackId, clear) {
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  feedback(feedbackId, 'Working…');
  try {
    const result = await request(path, value);
    feedback(feedbackId, result.message);
    if (clear) clear();
    if (result.pairing_url) {
      $('pairing-link').href = result.pairing_url;
      $('pairing-link').hidden = false;
    }
    await refresh();
  } catch (error) {
    feedback(feedbackId, error.message, true);
  } finally {
    button.disabled = false;
  }
}

$('project-form').addEventListener('submit', event => {
  event.preventDefault();
  submit(event.currentTarget, 'project', {path: $('project-path').value}, 'project-feedback');
});
$('provider-name').addEventListener('change', () => {
  $('provider-name').dataset.touched = 'true';
  updateProviderFields();
});
$('provider-form').addEventListener('submit', event => {
  event.preventDefault();
  submit(event.currentTarget, 'provider', {
    name: $('provider-name').value, key: $('provider-key').value,
    model: $('provider-model').value, endpoint: $('provider-endpoint').value
  }, 'provider-feedback', () => { $('provider-key').value = ''; });
});
$('telegram-form').addEventListener('submit', event => {
  event.preventDefault();
  submit(event.currentTarget, 'telegram', {token: $('telegram-token').value},
    'telegram-feedback', () => { $('telegram-token').value = ''; });
});
$('refresh').addEventListener('click', refresh);
$('update-check').addEventListener('click', async () => {
  $('update-check').disabled = true;
  feedback('update-feedback', 'Checking GitHub…');
  try {
    const result = await request('update-check', {});
    feedback('update-feedback', result.message);
    await refresh();
  } catch (error) {
    feedback('update-feedback', error.message, true);
  } finally {
    $('update-check').disabled = false;
  }
});
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = 'Copy'; }, 1800);
  } catch (_) { button.textContent = 'Copy unavailable'; }
}));
if (nativeDesktop || location.protocol !== 'file:') {
  if (nativeDesktop) $('desktop-feedback').textContent = 'Reading local status…';
  if (nativeDesktop && activeTab === 'usage') refreshUsage();
  refresh();
}

function renderJobs() {
  const query = $('job-search').value.toLowerCase();
  const matches = savedJobs.filter(job => [job.title, job.project, job.backend].join(' ').toLowerCase().includes(query));
  const groups = new Map();
  for (const job of matches) {
    const name = job.project || 'Other jobs';
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(job);
  }
  $('tasks-list').replaceChildren();
  for (const [name, jobs] of groups) {
    const heading = document.createElement('h4'); heading.textContent = name;
    $('tasks-list').append(heading);
    for (const job of jobs) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'task-row' + (job.id === selectedTask ? ' selected' : '');
      button.dataset.taskId = job.id;
      const title = document.createElement('strong'); title.textContent = job.title || job.id;
      const detail = document.createElement('small'); detail.textContent = job.backend + ' · ' + job.status;
      button.append(title, detail); $('tasks-list').append(button);
    }
  }
  if (!matches.length) $('tasks-list').append(checkItem('No matching jobs', 'warn', 'Try another title or project.'));
}

async function refreshWorkflowLibrary(more = false) {
  const kind = $('workflow-kind').value;
  try {
    const result = await request('workflows', {kind, offset: more ? workflowOffset : 0});
    if ($('workflow-kind').value !== kind) return;
    workflowOffset = result.next_offset;
    if (!more) $('workflow-library').replaceChildren();
    for (const item of result.items) {
      const card = document.createElement('details'); card.className = 'library-card';
      const title = document.createElement('summary'); title.textContent = item.title + ' · ' + item.status;
      const meta = document.createElement('p'); meta.className = 'fine';
      meta.textContent = [item.id, item.channel, item.revision != null ? 'Revision ' + item.revision : '', item.detail].filter(Boolean).join(' · ');
      card.append(title, meta);
      if (item.request) { const body = document.createElement('div'); renderMarkdown(body, item.request); card.append(body); }
      for (const step of item.steps || []) {
        card.append(checkItem(step.id, step.status === 'accepted' ? 'ok' : 'warn', step.status + ' · attempts ' + step.attempts));
      }
      $('workflow-library').append(card);
    }
    $('workflow-count').textContent = result.total + ' saved records at the connected data location';
    $('workflow-more').hidden = workflowOffset === null;
    if (!result.total) $('workflow-library').append(checkItem('No records in this category', 'warn', 'Try another category, or connect the existing service history in System.'));
  } catch (error) { $('workflow-count').textContent = 'Could not read workflows: ' + error.message; }
}

async function refreshTools() {
  try {
    const result = await request('automation-tools');
    for (const [target, items] of [['capability-actions', result.actions || []], ['capability-executors', result.executors || []]]) {
      $(target).replaceChildren(...items.map(item => {
        const card = document.createElement('details'); card.className = 'library-card';
        const heading = document.createElement('summary'); heading.textContent = item.description || item.id;
        const detail = document.createElement('p'); detail.textContent = item.availability || (item.available ? 'Configured locally' : item.blocker || 'Unavailable');
        const route = document.createElement('p'); route.className = 'fine'; route.textContent = item.route || item.permissions || item.grant_boundary;
        const id = document.createElement('code'); id.textContent = item.id;
        card.append(heading, detail, route, id); return card;
      }));
    }
    $('automation-tools').replaceChildren(...result.tools.map(tool => {
      const card = document.createElement('details'); card.className = 'library-card';
      const heading = document.createElement('summary'); heading.textContent = (tool.title || tool.id) + ' · v' + tool.version + ' · ' + (tool.available ? 'Detected' : 'Unavailable');
      const evidence = document.createElement('p'); evidence.textContent = tool.id + ' · ' + tool.availability_evidence;
      const description = document.createElement('p'); description.textContent = (tool.criteria || []).join(' ');
      const limits = document.createElement('p'); limits.className = 'fine';
      limits.textContent = 'Inputs: ' + tool.input_types.join(', ') + '. Outputs: ' + (tool.output_type || Object.values(tool.outputs || {}).join(', ')) + '. Limit: ' + tool.seconds + ' seconds. ' + (tool.permissions || 'Exact inputs and reviewed plan required.');
      card.append(heading, evidence, description, limits); return card;
    }));
  } catch (error) { $('automation-tools').replaceChildren(checkItem('Tools unavailable', 'fail', error.message)); }
}

async function refreshApprovalInbox() {
  try {
    const result = await request('approval-inbox');
    $('approval-inbox').replaceChildren(...result.items.map(item => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'task-row approval-link';
      button.textContent = item.title + ' · ' + item.count + ' pending';
      button.addEventListener('click', async () => {
        showTab('tasks', true); $('task-panel').hidden = false;
        try { await showTask(item.task_id); $('task-approvals').scrollIntoView({block: 'nearest'}); }
        catch (error) { feedback('task-feedback', error.message, true); }
      }); return button;
    }));
    $('approval-inbox-label').textContent = result.items.length ? 'Needs your decision' : 'No pending approvals';
  } catch (error) { $('approval-inbox-label').textContent = 'Approvals unavailable — refresh Jobs'; }
}
