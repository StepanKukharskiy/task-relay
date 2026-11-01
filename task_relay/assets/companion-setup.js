/* Setup and app-open startup follow saved local connection state. */
globalThis.RelaySetup = {
  shouldAutoStart(info) {
    return !info.setup?.setup_error && this.step(info)?.action === 'start';
  },
  step(info) {
    const setup = info.setup || {}, service = info.service || {}, telegram = setup.telegram || {};
    if (service.connectable) return {id: 'existing', number: 1, title: 'Your Relay installation is already here', detail: 'Reuse its saved connections and history. This does not restart or replace its service.', action: 'connect', label: 'Use existing setup'};
    const ai = Object.values(setup.providers || {}).some(Boolean) || setup.selected_provider === 'later';
    if (!ai) return {id: 'ai', number: 1, title: 'Connect your AI', detail: 'Choose Codex with ChatGPT sign-in, connect an API provider, or use existing agent tasks. Codex needs Relay’s qualified local runtime; account limits apply.', form: 'provider-settings'};
    if (!service.healthy) {
      if (service.error || service.loaded) return {id: 'service', number: 3, title: 'Check the Relay connection', detail: service.error || 'The local worker has not confirmed a healthy start. Check service diagnostics below. Telegram is optional and will not fix a local startup failure.', action: 'troubleshoot', label: 'Check connection'};
      if (service.owner === 'other') return {id: 'service', number: 3, title: 'Review your existing service', detail: 'An existing service owns this connection. Review its handoff before the companion starts managing it.', action: 'handoff', label: 'Review service handoff'};
      return {id: 'service', number: 2, title: 'Start Relay on this Mac', detail: 'Relay runs in the background. You can start tasks in Jobs and add messenger connections separately.', action: 'start', label: 'Start Relay'};
    }
    return null;
  }
};
