/* Only the installed native host can request the three fixed browser operations. */
'use strict';
let port = null;
let enabled = false;
let managedTab = null;
let retry = null;
let chain = Promise.resolve();
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function safeURL(value) {
  const u = new URL(value);
  if (u.protocol !== 'https:' || !['www.perplexity.ai', 'perplexity.ai'].includes(u.host) ||
      u.username || u.password || u.search || u.hash ||
      !/^\/(?:search\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?$/.test(u.pathname)) {
    throw new Error('Only Perplexity home and saved Search conversations are allowed.');
  }
  return u.href;
}

function badge(text, title) {
  browser.browserAction.setBadgeText({text});
  browser.browserAction.setTitle({title});
}

async function pageCall(message, currentPort) {
  if (!enabled || port !== currentPort || managedTab === null) throw new Error('Browser connection ended.');
  const tab = await browser.tabs.get(managedTab);
  safeURL(tab.url);
  return browser.tabs.sendMessage(managedTab, {relay: true, ...message});
}

async function command(message, currentPort) {
  if (!message || typeof message.id !== 'string') throw new Error('Invalid native request.');
  if (message.action === 'open') {
    const url = safeURL(message.url);
    // Always create a worker tab; do not replace the user's selected tab or draft.
    const tab = await browser.tabs.create({url, active: false});
    managedTab = tab.id;
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (!enabled || currentPort !== port) throw new Error('Browser disconnected.');
      const current = await browser.tabs.get(managedTab);
      if (current.status === 'complete') {
        safeURL(current.url);
        await browser.tabs.executeScript(managedTab, {file: 'page.js'});
        return true;
      }
      await wait(250);
    }
    throw new Error('Perplexity did not load. Check the browser; no Search was submitted.');
  }
  if (!['snapshot', 'submit'].includes(message.action)) throw new Error('Unsupported native operation.');
  return pageCall(message, currentPort);
}

function connect() {
  if (!enabled || port) return;
  const current = browser.runtime.connectNative('ai.task_relay.perplexity');
  port = current;
  current.onMessage.addListener(message => {
    if (current !== port || !enabled) return;
    if (message.action === 'idle') {
      badge('ON', 'Task Relay connected · click to disconnect');
      retry = setTimeout(() => { if (port === current && enabled) current.postMessage({action: 'poll'}); }, 2000);
      return;
    }
    chain = chain.then(async () => {
      try {
        const value = await command(message, current);
        if (port === current && enabled) current.postMessage({id: message.id, value});
      } catch (error) {
        if (port === current && enabled) current.postMessage({id: message.id, error: error.message});
      }
    });
  });
  current.onDisconnect.addListener(() => {
    if (port !== current) return;
    port = null;
    badge('!', 'Task Relay disconnected: ' + (current.error?.message || 'native worker stopped'));
    if (enabled) retry = setTimeout(connect, 5000);
  });
  current.postMessage({action: 'poll'});
}

browser.browserAction.onClicked.addListener(async () => {
  enabled = !enabled;
  await browser.storage.local.set({enabled});
  clearTimeout(retry);
  if (enabled) connect();
  else {
    const old = port; port = null;
    if (old) old.disconnect();
    badge('', 'Connect Task Relay to Perplexity Search');
  }
});

browser.storage.local.get('enabled').then(saved => {
  enabled = saved.enabled === true;
  if (enabled) connect();
});
