"""Hidden local key entry and read-only model-catalog verification."""
import getpass
import json
import os
from pathlib import Path
from task_relay.gemini import Client, DATA, DEFAULT_MODELS, ProviderError, atomic_bytes, read_config


def main():
    os.umask(0o077)
    print('Create a Gemini API key at https://aistudio.google.com/apikey if you do not have one.')
    print('Setup checks the model catalog only. It does not generate content or enable billing.')
    old = read_config() or {}
    key = getpass.getpass('Gemini API key (hidden; Return keeps a saved key): ').strip() or old.get('api_key')
    if not key:
        raise SystemExit('No key entered. Setup was not changed.')
    from task_relay.providers import configure_gemini, stored
    try:
        models = configure_gemini(key)
        names = stored('gemini').get('catalog', [])
    except (ProviderError, ValueError) as exc:
        raise SystemExit(f'Could not validate the key ({getattr(exc, "status", "model catalog unavailable")}). Setup was not changed.') from None
    print('\nGemini key saved. No bridge restart is needed.')
    for cap, model in models.items():
        print(f'{cap}: {model}' + ('' if model in names else ' — not listed; configure an available model before use'))
    print('\nModel listings do not guarantee paid-tier, quota, or regional access. Media calls may be billed by Google.')
    print('In Telegram: /new gemini "/absolute/project/folder" Task title\nThen send an instruction, or /image, /speak, /video followed by a prompt.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nSetup cancelled.')
