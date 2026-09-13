/* Setup follows saved connection state; opening a step never starts work. */
globalThis.RelaySetup = {
  step(info) {
    const setup = info.setup || {}, service = info.service || {}, telegram = setup.telegram || {};
    if (service.connectable) return {id: 'existing', number: 1, title: 'Your Relay installation is already here', detail: 'Reuse its saved connections and history. This does not restart or replace its service.', action: 'connect', label: 'Use existing setup'};
    const ai = Object.values(setup.providers || {}).some(Boolean) || setup.selected_provider === 'later';
    if (!ai) return {id: 'ai', number: 1, title: 'Connect your AI', detail: 'Choose an AI provider and add your API key, or use agent tasks you already have. Provider usage may be billed by your provider.', form: 'provider-settings'};
    if (!telegram.configured) return {id: 'telegram', number: 2, title: 'Connect Telegram', detail: 'Create a dedicated bot, then paste its token below. Telegram is the supported first-time setup path for this beta.', form: 'telegram-settings'};
    if (telegram.paired) return null;
    if (!service.healthy) {
      if (service.error || service.loaded) return {id: 'service', number: 3, title: 'Check the Relay connection', detail: service.error || 'The service is loaded but has not confirmed a healthy connection. Your saved setup is retained.', action: 'troubleshoot', label: 'Check connection'};
      if (service.owner === 'other') return {id: 'service', number: 3, title: 'Review your existing service', detail: 'An existing service owns this connection. Review its handoff before the companion starts managing it.', action: 'handoff', label: 'Review service handoff'};
      return {id: 'service', number: 3, title: 'Start Relay on this Mac', detail: 'Relay will run in the background and reconnect when you log in. Starting it enables your configured messenger connection.', action: 'start', label: 'Start Relay'};
    }
    return {id: 'pair', number: 4, title: 'Pair your Telegram account', detail: 'Open the private pairing link and tap Start in Telegram. Return here to see pairing confirmed. You can then send your first instruction; that may use paid AI services.', action: 'pair', label: 'Pair in Telegram'};
  }
};
