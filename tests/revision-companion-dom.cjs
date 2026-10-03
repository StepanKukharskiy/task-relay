// Controlled companion fixture: no Relay service, account or provider calls.
const assert = require('node:assert/strict');
const path = require('node:path');
if (process.env.TASK_RELAY_LOCAL_BROWSER_FIXTURE !== '1') {
  process.stdout.write('Local browser fixture skipped.\n');
  process.exit(0);
}
const { chromium } = require(process.env.TASK_RELAY_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({
    ...(process.env.TASK_RELAY_BROWSER_BINARY
      ? {executablePath: process.env.TASK_RELAY_BROWSER_BINARY} : {}),
    headless: true,
  });
  try {
    const page = await browser.newPage({viewport: {width: 480, height: 800}});
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.addInitScript(() => {
      window.calls = [];
      window.deletedPipelines = [];
      window.candidates = [];
      window.fixture = {
        setup: {version: 'fixture', providers: {gemini: true}, selected_provider: 'gemini',
          telegram: {configured: true, paired: true}, doctor: {checks: []}},
        service: {healthy: true, loaded: true}, conversation: {url: null},
        browser: {enabled: false, available: true}, channels: {}, messages: {},
        decisions: {items: []}, folders: [], model_defaults: {revision: 0, capabilities: []},
      };
      window.revision = {
        kind: 'parts_translation', candidate_artifact: 'candidate-fixture',
        job: 'job-fixture', title: 'Parts catalog revision',
        candidate_sha256: 'a'.repeat(64), candidate_path: '/tmp/review/candidate.xlsx',
        verified: true, error: null,
        plan: {digest: 'b'.repeat(64),
          affected: [{part_number: '10014', translation_cell: 'Pilot!F8', before: 'CLAMP',
            after: 'BOLT', reason: 'Source name changed; review required.',
            saved_catalog_title: 'Clamp, Hose', saved_evidence_url: 'https://example.org/10014'}],
          unaffected: [{part_number: '10038A', translation_cell: 'Pilot!F9',
            reason: 'Exact source unchanged.'}],
          unknown: [{part_number: '002-15381-00-00', translation_cell: 'Pilot!F2',
            reason: 'Originally unresolved.'}], coverage: 'Explicit reviewed links only.'},
        checks: {changed_cells: ['Pilot!D8', 'Pilot!F8'], untouched_cells_verified: 236},
        evidence_links: [{output_location: 'Pilot!F8', source_location: 'Лист1!B7',
          review_state: 'подтверждено', evidence: 'Clamp, Hose',
          evidence_url: 'https://example.org/10014'}],
        review: null, selection: null, can_review: true, can_select: false,
      };
      window.__TAURI__ = {
        core: {invoke: async (command, args) => {
          if (command === 'companion_reveal_revision') return null;
          const {path: action, value} = args;
          if (action === 'companion-status') return structuredClone(window.fixture);
          if (action === 'revision-candidates') return {items: structuredClone(window.candidates)};
          if (action === 'tasks') return {tasks: [{id:'task-fixture', title:'Fixture task',
            status:'completed', backend:'openai', project:'catalog'}], total:1, next_offset:null};
          if (action === 'workflows') return {items: value.kind === 'pipelines' && !window.deletedPipelines.length ?
            [{id:'job-fixture', title:'Parts catalog', status:'completed', request:'Translate names',
              job_view:'/tmp/job-fixture/.relay/job.sqlite'}] : [], total:value.kind === 'pipelines' && !window.deletedPipelines.length ? 1 : 0,
            next_offset:null};
          if (action === 'pipeline-delete-pending') return {items: []};
          if (action === 'pipeline-delete-preview') return {id:value.id, title:'Parts catalog',
            plans:[], runs:[], counts:{relay_pipelines:1}, blockers:[], digest:'c'.repeat(64)};
          if (action === 'pipeline-delete') { window.deletedPipelines.push(value.id); return {id:value.id,status:'complete'}; }
          if (action === 'revision-detail') return structuredClone(window.revision);
          if (action === 'revision-decide') {
            window.calls.push(structuredClone(value));
            if (value.verb === 'select') {
              window.revision.selection = {selected_by: value.actor,
                candidate_sha256: value.expected_sha256};
              window.revision.can_select = false;
            } else {
              window.revision.review = {decision: value.verb, reviewer: value.actor,
                note: value.note};
              window.revision.can_review = false;
              window.revision.can_select = value.verb === 'accept';
            }
            return {detail: structuredClone(window.revision), warning: null};
          }
          return {};
        }}, event: {listen: async () => {}}, opener: {openUrl: async () => {}},
      };
    });
    const assets = path.resolve(__dirname, '..', 'task_relay', 'assets');
    await page.route('http://127.0.0.1:33223/**', route => {
      const name = path.basename(new URL(route.request().url()).pathname) || 'companion.html';
      if (!['companion.html', 'companion.js', 'companion-setup.js',
            'companion-updates.js', 'companion.css', 'messages-icon.png'].includes(name)) {
        return route.fulfill({status: 404, body: ''});
      }
      return route.fulfill({path: path.join(assets, name)});
    });
    await page.goto('http://127.0.0.1:33223/');
    assert.equal(await page.locator('#review-revisions').isVisible(), false);
    await page.getByRole('button', {name: 'Saved work…'}).click();
    assert.match(await page.locator('#saved-work-list').innerText(), /Fixture task/);
    await page.locator('#saved-work-kind').selectOption('pipelines');
    assert.match(await page.locator('#saved-work-list').innerText(), /\.relay\/job\.sqlite/);
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: 'Delete…'}).click();
    assert.deepEqual(await page.evaluate(() => window.deletedPipelines), ['job-fixture']);
    assert.match(await page.locator('#saved-work-list').innerText(), /No saved work/);
    await page.getByRole('button', {name: 'Done'}).last().click();
    await page.evaluate(() => { window.candidates = [{kind: 'parts_translation',
      status: 'awaiting_review', job: 'job-fixture', candidate_artifact: 'candidate-fixture'}]; });
    await page.getByRole('button', {name: 'Refresh status'}).click();
    await page.getByRole('button', {name: 'Review revision candidates…'}).click();
    await page.getByRole('button', {name: 'parts translation · awaiting_review · job-fixture'}).click();
    assert.match(await page.locator('#revision-detail').innerText(), /Clamp, Hose/);
    assert.match(await page.locator('#revision-detail').innerText(), /Лист1!B7/);
    assert.match(await page.locator('#revision-detail').innerText(), /Unknown or unresolved · 1/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#revisions').screenshot({path: 'outputs/o14-motorcycle-revision/review-screen.png'});
    await page.locator('#revision-detail input:not([type=checkbox])').fill('Independent reviewer');
    await page.locator('#revision-detail textarea').fill('Checked exact candidate and saved source.');
    await page.locator('#revision-detail input[type=checkbox]').check();
    await page.getByRole('button', {name: 'Record accepted review'}).click();
    assert.match(await page.locator('#revision-detail').innerText(), /accept · Independent reviewer/);
    await page.locator('#revision-detail input:not([type=checkbox])').fill('User');
    await page.locator('#revision-detail input[type=checkbox]').check();
    await page.getByRole('button', {name: 'Select exact candidate'}).click();
    assert.match(await page.locator('#revision-detail').innerText(), /Selected by: User/);
    const calls = await page.evaluate(() => window.calls);
    assert.deepEqual(calls.map(call => call.verb), ['accept', 'select']);
    assert.deepEqual([...new Set(calls.map(call => call.expected_sha256))], ['a'.repeat(64)]);
    assert.notEqual(calls[0].request_id, calls[1].request_id);
    assert.deepEqual(errors, []);
    process.stdout.write('Companion revision preview and separate decisions passed.\n');
  } finally {
    await browser.close();
  }
})().catch(error => { process.stderr.write(String(error.stack || error) + '\n'); process.exitCode = 1; });
