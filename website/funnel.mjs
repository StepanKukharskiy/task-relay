// Website-only request counts. No cookies, visitor IDs, request bodies or Skill telemetry.
export const skillPath = '/skills/excel-to-powerpoint';
export const articlePath = '/guides/excel-to-powerpoint';
export const editorialUrl = 'https://stepankukharskiy.com/ai-work/excel-to-powerpoint-automation';
const campaigns = new Set(['direct', 'medium-excel-to-powerpoint-v1', 'guide-excel-to-powerpoint-v1', 'medium-excel-to-powerpoint-v2', 'guide-excel-to-powerpoint-v2', 'medium-excel-to-powerpoint-v3', 'personal-excel-to-powerpoint-v3']);
export const guideCampaign = 'guide-excel-to-powerpoint-v2';
const events = new Set(['article_request', 'skill_page_request', 'skill_download_request', 'example_download_request', 'relay_cta_request', 'relay_download_request']);

export function campaignFor(url) {
  const explicit = url.searchParams.get('campaign');
  if (explicit !== null) return campaigns.has(explicit) ? explicit : 'direct';
  const version = url.searchParams.get('utm_campaign');
  if (!['excel-to-powerpoint-v1', 'excel-to-powerpoint-v2', 'excel-to-powerpoint-v3'].includes(version) || url.searchParams.get('utm_medium') !== 'article') return 'direct';
  const source = url.searchParams.get('utm_source');
  const candidate = source + '-' + version;
  return campaigns.has(candidate) ? candidate : 'direct';
}

export function countRequest(request, event, campaign, {enabled = process.env.TASK_RELAY_FUNNEL_ANALYTICS !== 'off', log = console.log, now = new Date()} = {}) {
  if (!enabled || request.method !== 'GET' || request.headers.dnt === '1' || request.headers['sec-gpc'] === '1') return false;
  if (/bot|crawler|spider|preview|headless|curl|wget|python|node|undici/i.test(request.headers['user-agent'] || '') || request.headers.purpose === 'prefetch' || request.headers['sec-purpose']?.includes('prefetch')) return false;
  if (!events.has(event) || !campaigns.has(campaign)) throw Error('Unknown funnel dimension');
  log(JSON.stringify({schema: 'skill-funnel.v1', day: now.toISOString().slice(0, 10), skill: 'excel-to-powerpoint', campaign, event}));
  return true;
}

export function renderSkillPage(body, campaign) {
  if (!campaigns.has(campaign)) throw Error('Unknown campaign');
  return body.replaceAll('{{skillCampaign}}', campaign);
}

export function attributeRelayLinks(body, release, campaign) {
  if (!campaigns.has(campaign)) throw Error('Unknown campaign');
  for (const [kind, file] of [['dmg', 'arm64.dmg'], ['source', 'source.tar.gz']]) {
    body = body.replaceAll(`href="${release.assets[kind].url}"`, `href="/downloads/latest/${file}?skill=excel-to-powerpoint&campaign=${campaign}"`);
  }
  return body;
}
