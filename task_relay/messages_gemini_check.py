"""Minimal live check of the already-configured Gemini connection. Prints no key."""
from task_relay import gemini


def main():
    config = gemini.read_config()
    if not config:
        raise SystemExit('Gemini is not connected.')
    model = gemini.model_name(config.get('models', {}).get('text', gemini.DEFAULT_MODELS['text']))
    client = gemini.Client(config['api_key'])
    try:
        result = client.request('models/' + model + ':generateContent', {
            'contents': [{'role': 'user', 'parts': [{'text': 'Reply with exactly: GEMINI_MESSAGES_OK'}]}],
            'generationConfig': {'maxOutputTokens': 512}})
        answer = ''.join(p.get('text', '') for c in result.get('candidates', [])
                         for p in c.get('content', {}).get('parts', []) if not p.get('thought'))
        print('Configured model:', model)
        print('Live check:', 'passed' if answer.strip() == 'GEMINI_MESSAGES_OK' else 'response received; marker not matched')
        if answer.strip() != 'GEMINI_MESSAGES_OK':
            raise SystemExit(1)
    except gemini.ProviderError as exc:
        raise SystemExit(f'Gemini check failed: {exc.status}; uncertain={exc.uncertain}') from None


if __name__ == '__main__':
    main()
