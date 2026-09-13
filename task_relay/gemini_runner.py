"""One bounded Gemini request, or retrieval of an already submitted video job."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import wave

from task_relay import gemini
from task_relay import file_tools
from task_relay.backends import finish


class Cancelled(Exception):
    pass


def content(response):
    candidates = response.get('candidates', [])
    if not candidates:
        raise ValueError('Google returned no candidate (the request may have been filtered).')
    candidate = candidates[0]
    reason = candidate.get('finishReason', 'STOP')
    if reason != 'STOP':
        raise ValueError('Google did not return a complete result. It may have reached an output limit or filtered the response.')
    result = candidate.get('content', {})
    if not result.get('parts'):
        raise ValueError('Google returned an empty result.')
    return result


def make_request(state, job, run):
    cap = run['capability']
    options = json.loads(run['options_json'])
    if cap == 'video':
        return {'instances': [{'prompt': job['prompt']}], 'parameters': {
            'aspectRatio': options['aspect_ratio'], 'durationSeconds': options['duration_seconds'], 'resolution': '720p'}}
    parts = [{'text': job['prompt']}]
    for ref in options['references']:
        data = Path(ref['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != ref['sha256']:
            raise ValueError('A reference changed after this job was queued. Attach it again.')
        parts.append({'text': f"Reference {ref['id']}: {ref['filename']}"})
        if ref['mime'] == 'text/plain':
            parts.append({'text': data.decode('utf-8')})
        else:
            parts.append({'inlineData': {'mimeType': ref['mime'], 'data': base64.b64encode(data).decode()}})
    current = {'role': 'user', 'parts': parts}
    history = []
    rows = []
    if cap in ('text', 'image'):
        rows = state.db.execute('SELECT * FROM gemini_history WHERE thread_id=? AND capability=? ORDER BY created_at', (job['thread_id'], cap)).fetchall()
        for previous in rows:
            history.append(json.loads(Path(previous['input_path']).read_text()))
            history.append(content(json.loads(Path(previous['response_path']).read_text())))
    cfg = {'maxOutputTokens': options['max_output_tokens']}
    if cap == 'speech':
        cfg = {'responseModalities': ['AUDIO'], 'speechConfig': {
            'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': options['voice']}}}}
    elif cap == 'image':
        cfg.update(responseModalities=['TEXT', 'IMAGE'], imageConfig={'aspectRatio': options['aspect_ratio']})
    payload = {'contents': history + [current], 'generationConfig': cfg}
    if cap == 'text':
        payload['systemInstruction'] = {'parts': [{'text':
            'You are assisting through a private Telegram task relay. Only supplied references and this conversation are available. '
            'You have no shell, filesystem, CAD, or BIM tools. Do not claim to have inspected other project files or performed tool actions. '
            'When reviewing drawings, cite the provided filename and page or visible location; distinguish observations from inferences. '
            'Do not claim validated dimensions, quantities, geometry, or code compliance without supplied evidence.'}]}
        if options.get('workspace'):
            from task_relay.api_providers import FILE_SYSTEM
            payload['systemInstruction']['parts'][0]['text'] = FILE_SYSTEM + ' You can also inspect the supplied reference attachments.'
            payload['tools'] = [{'functionDeclarations': [
                {'name': d['name'], 'description': d['description'], 'parametersJsonSchema': d['parameters']}
                for d in file_tools.DEFINITIONS]}]
    if len(json.dumps(payload).encode()) > gemini.MAX_CONTEXT and cap in ('text','image') and rows:
        # Start a new native image context. Never splice or strip signed model
        # turns: archived provider responses remain byte-for-byte intact.
        transcript, sources, latest_images = [], [], []
        for previous in rows:
            old_job = state.db.execute('SELECT prompt FROM backend_jobs WHERE id=?', (previous['job_id'],)).fetchone()
            native = content(json.loads(Path(previous['response_path']).read_text()))
            transcript.append({'request': old_job['prompt'] if old_job else
                json.loads(Path(previous['input_path']).read_text())['parts'][0]['text'],
                'response': '\n'.join(p['text'] for p in native['parts'] if isinstance(p.get('text'), str) and not p.get('thought'))})
            images = [p.get('inlineData') or p.get('inline_data') for p in native['parts'] if not p.get('thought')]
            images = [i for i in images if i and i.get('mimeType', i.get('mime_type', '')).startswith('image/')]
            if images:
                latest_images = [{'inlineData': {'mimeType': i.get('mimeType', i.get('mime_type')), 'data': i['data']}} for i in images]
            sources.append({'job_id': previous['job_id'], **{k: {'path': previous[k],
                'sha256': hashlib.sha256(Path(previous[k]).read_bytes()).hexdigest()}
                for k in ('input_path', 'response_path')}})
        from . import context_handoff
        can_read=cap=='text' and bool(options.get('workspace'))
        if can_read:
            definition=context_handoff.DEFINITION
            payload['tools'][0]['functionDeclarations'].append({'name':definition['name'],'description':definition['description'],'parametersJsonSchema':definition['parameters']})
        def render(text):
            return {**payload,'contents':[{'role':'user','parts':[{'text':text},*latest_images,*parts]}]}
        payload=context_handoff.fit(transcript,render,gemini.MAX_CONTEXT-(min(64000,gemini.MAX_CONTEXT//4) if can_read else 0),Path(run['response_path']).with_suffix('.context.json'),
            provider='gemini',sources=sources,can_read=can_read)
    if len(json.dumps(payload).encode()) > gemini.MAX_CONTEXT:
        raise ValueError('The current references and instructions exceed the request byte limit even after an image context handoff. Select fewer references or a smaller image; no provider request was sent.')
    return payload


def text_with_tools(state, job, run, client, check):
    """Persist Gemini's native tool conversation; canonical response holds the final answer."""
    from task_relay.api_providers import MAX_TOOL_ROUNDS, MAX_TOOL_CALLS
    jid = job['id']
    final = Path(run['response_path'])
    current = state.db.execute('SELECT * FROM gemini_tool_runs WHERE job_id=?', (jid,)).fetchone()
    if not current:
        if run['stage'] != 'prepared':
            raise gemini.ProviderError('unconfirmed-submission', uncertain=True)
        payload = make_request(state, job, run)
        gemini.atomic_bytes(final.with_suffix('.input.json'), json.dumps(payload['contents'][-1]).encode())
        with state.db:
            state.db.execute('INSERT OR IGNORE INTO gemini_tool_runs(job_id,request_json,response_path) VALUES (?,?,?)',
                             (jid, json.dumps(payload), str(final.with_suffix('.step-0.json'))))
    while True:
        check()
        current = state.db.execute('SELECT * FROM gemini_tool_runs WHERE job_id=?', (jid,)).fetchone()
        payload = json.loads(current['request_json'])
        path = Path(current['response_path'])
        if path.is_file():
            response = json.loads(path.read_text())
        else:
            if current['stage'] != 'prepared':
                raise gemini.ProviderError('unconfirmed-submission', uncertain=True)
            check()
            with state.db:
                claimed = state.db.execute("UPDATE gemini_tool_runs SET stage='sending' WHERE job_id=? AND step=? AND stage='prepared' AND EXISTS (SELECT 1 FROM backend_jobs WHERE id=? AND status='running' AND cancel=0) AND EXISTS (SELECT 1 FROM gemini_runs WHERE job_id=? AND stage='prepared')",
                                           (jid, current['step'], jid, jid)).rowcount
                if claimed:
                    state.db.execute("UPDATE gemini_runs SET stage='sending',attempts=attempts+1 WHERE job_id=?", (jid,))
            if not claimed:
                raise gemini.ProviderError('submission-already-claimed', uncertain=True)
            response = client.request('models/' + gemini.model_name(run['model']) + ':generateContent', payload)
            gemini.atomic_bytes(path, json.dumps(response).encode())
        with state.db:
            state.db.execute('INSERT OR IGNORE INTO api_steps VALUES (?,?,?)',
                             (jid, current['step'], json.dumps(response.get('usageMetadata', {}))))
        check()
        native = content(response)
        calls = [p['functionCall'] for p in native['parts'] if 'functionCall' in p]
        if not calls:
            gemini.atomic_bytes(final, json.dumps(response).encode())
            return response
        used = state.db.execute('SELECT count(*) FROM api_tool_calls WHERE job_id=? AND step<?', (jid, current['step'])).fetchone()[0]
        if current['step'] >= MAX_TOOL_ROUNDS or used + len(calls) > MAX_TOOL_CALLS:
            raise ValueError('File tool budget reached. Please narrow the request.')
        if any(not isinstance(c, dict) or not isinstance(c.get('name'), str) or not isinstance(c.get('args'), dict) for c in calls):
            raise ValueError('Google returned malformed function calls; no file tools were executed for this response.')
        ids = [c.get('id', str(index)) for index, c in enumerate(calls)]
        if any(not isinstance(cid, str) or not cid for cid in ids) or len(set(ids)) != len(ids):
            raise ValueError('Google returned invalid or duplicate function-call identifiers.')
        results = []
        for call, cid in zip(calls, ids):
            check()
            raw = json.dumps(call['args'])
            saved = state.db.execute('SELECT result_json FROM api_tool_calls WHERE job_id=? AND step=? AND call_id=?',
                                     (jid, current['step'], cid)).fetchone()
            if saved:
                value = json.loads(saved[0])
            else:
                offered={d['name'] for group in payload.get('tools',[]) for d in group.get('functionDeclarations',[])}
                if call['name']=='context_read' and call['name'] in offered:
                    from . import context_handoff
                    value=context_handoff.read(final.with_suffix('.context.json'),raw)
                else:
                    value = file_tools.execute(json.loads(run['options_json'])['workspace'], call['name'], raw,
                                               (gemini.DATA, state.media_dir.parent))
                with state.db:
                    state.db.execute('INSERT OR IGNORE INTO api_tool_calls VALUES (?,?,?,?,?,?)',
                                     (jid, current['step'], cid, call['name'], raw, json.dumps(value, ensure_ascii=False)))
            result = {'name': call['name'], 'response': value}
            if 'id' in call:
                result['id'] = call['id']
            results.append({'functionResponse': result})
        # Retain every returned part, including opaque thought signatures.
        payload['contents'].extend([native, {'role': 'user', 'parts': results}])
        if current['step'] + 1 >= MAX_TOOL_ROUNDS or used + len(calls) >= MAX_TOOL_CALLS:
            payload['toolConfig'] = {'functionCallingConfig': {'mode': 'NONE'}}
            payload['systemInstruction']['parts'][0]['text'] += '\nFile tool budget reached. Give a final answer from available evidence and explain unfinished work.'
        encoded = json.dumps(payload)
        if len(encoded.encode()) > gemini.MAX_CONTEXT:
            raise ValueError('This conversation exceeds the 16 MB request limit. Start a new task with a concise handoff.')
        check()
        with state.db:
            advanced = state.db.execute("UPDATE gemini_tool_runs SET step=step+1,stage='prepared',request_json=?,response_path=? WHERE job_id=? AND step=?",
                                        (encoded, str(final.with_suffix(f".step-{current['step'] + 1}.json")), jid, current['step'])).rowcount
            if advanced:
                state.db.execute("UPDATE gemini_runs SET stage='prepared' WHERE job_id=?", (jid,))
        if not advanced:
            raise gemini.ProviderError('submission-already-claimed', uncertain=True)


def save_outputs(state, job, run, response, client):
    cap, jid, tid = run['capability'], job['id'], job['thread_id']
    title = state.db.execute('SELECT title FROM watched WHERE id=?', (tid,)).fetchone()[0]
    route = state.db.execute('SELECT source_id FROM speech_tasks WHERE thread_id=?', (tid,)).fetchone()
    if route and route[0]:
        title = state.db.execute('SELECT title FROM watched WHERE id=?', (route[0],)).fetchone()[0]
    if title in ('Speech', 'Gemini task'):
        title = job['prompt'].splitlines()[0][:80]
    slug = re.sub(r'[^\w-]+', '-', title.lower(), flags=re.UNICODE).strip('-_')[:64] or 'speech'
    slug = slug.encode('utf-8')[:160].decode('utf-8', errors='ignore')
    speech_stem = f'{slug}-{time.strftime("%Y%m%d-%H%M%S", time.localtime(job["created_at"]))}-{jid[:8]}'
    # Outputs always stay in this bridge's output folder, never an arbitrary cwd.
    folder = gemini.GENERATED / tid.split(':')[-1] / jid
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    outputs, text = [], ''
    if cap == 'video':
        video_response = response.get('response', {}).get('generateVideoResponse', {})
        samples = video_response.get('generatedSamples', [])
        if not samples or not samples[0].get('video', {}).get('uri'):
            raise ValueError('Google returned no video. The request may have been filtered.')
        path = folder / (speech_stem + '.mp4')
        if not path.is_file():
            client.download(samples[0]['video']['uri'], path)
        if path.read_bytes()[4:8] != b'ftyp':
            path.unlink(missing_ok=True)
            raise ValueError('The downloaded video is not a supported MP4 file.')
        outputs.append((path, 'video/mp4'))
        text = 'Video generated.'
    else:
        result = content(response)
        visible = [p for p in result['parts'] if not p.get('thought')]
        text = '\n'.join(p['text'] for p in visible if isinstance(p.get('text'), str))
        for part in visible:
            inline = part.get('inlineData') or part.get('inline_data')
            if not inline:
                continue
            mime = inline.get('mimeType', inline.get('mime_type', ''))
            data = base64.b64decode(inline['data'], validate=True)
            if len(data) > 50_000_000:
                raise ValueError('Generated file exceeds the 50 MB delivery limit.')
            if cap == 'image' and mime in ('image/png', 'image/jpeg', 'image/webp'):
                suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[mime]
                from task_relay.media import valid_image
                if not valid_image(data, suffix):
                    raise ValueError('Google returned invalid image data.')
                if len(outputs) >= 4:
                    raise ValueError('Google returned more than four images; this result needs local review.')
                path = folder / (f'{speech_stem}-image-{len(outputs)+1}' + suffix)
                gemini.atomic_bytes(path, data)
                outputs.append((path, mime))
            elif cap == 'speech' and mime.lower().startswith(('audio/l16', 'audio/pcm')):
                if not data or len(data) % 2:
                    raise ValueError('Google returned invalid PCM audio.')
                rate_match = re.search(r'rate=(\d+)', mime)
                rate = int(rate_match[1]) if rate_match else 24000
                if not 8000 <= rate <= 96000:
                    raise ValueError('Unsupported audio sample rate.')
                buffer = io.BytesIO()
                with wave.open(buffer, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(data)
                path = folder / (speech_stem + '.wav')
                gemini.atomic_bytes(path, buffer.getvalue())
                outputs.append((path, 'audio/wav'))
                ffmpeg = shutil.which('ffmpeg') or ('/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').is_file() else None)
                if ffmpeg:
                    mp3 = folder / (speech_stem + '.mp3')
                    try:
                        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(path), '-codec:a', 'libmp3lame', '-b:a', '128k', '-metadata', 'title=' + title, '-metadata', 'artist=Task Relay', str(mp3)],
                                       check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        outputs.append((mp3, 'audio/mpeg'))
                    except (OSError, subprocess.SubprocessError):
                        mp3.unlink(missing_ok=True)
                        text += '\nMP3 conversion unavailable; the original WAV is attached.'
                break
        if cap in ('image', 'speech') and not outputs:
            raise ValueError('Google returned no requested media. Check the capability model and prompt.')
        if cap == 'text' and not text.strip():
            raise ValueError('Google returned no visible text response.')
    usages = [json.loads(row[0]) for row in state.db.execute('SELECT usage_json FROM api_steps WHERE job_id=? ORDER BY step', (jid,))]
    metadata = {'job': jid, 'task': tid, 'capability': cap, 'model': run['model'],
                'prompt': job['prompt'], 'created_at': job['created_at'],
                'usage': {'steps': usages} if usages else response.get('usageMetadata', {}),
                'references': [{k: r[k] for k in ('id', 'filename', 'sha256')} for r in json.loads(run['options_json'])['references']],
                'files': [{'filename': p.name, 'mime': mime, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p, mime in outputs]}
    handoff=Path(run['response_path']).with_suffix('.context.json')
    if handoff.is_file():metadata['context_handoff']=json.loads(handoff.read_text())
    gemini.atomic_bytes(folder / 'manifest.json', json.dumps(metadata, indent=2).encode())
    with state.db:
        for path, mime in outputs:
            gemini.artifact(state, tid, jid, 'output', path, path.name, mime)
        state.db.execute('UPDATE gemini_runs SET usage_json=?,stage=? WHERE job_id=?',
                          (json.dumps(metadata['usage']), 'complete', jid))
    links = '\n'.join(f'[{p.name}](<{p}>)' for p, _ in outputs)
    note='\n\nContext continued from retained history; original requests and provider records were preserved.' if handoff.is_file() else ''
    return (text or f'{cap.capitalize()} generated.') + ('\n\n' + links if links else '') + note


def run_job(state, jid, parent_pid=None, client=None, sleep=time.sleep):
    job = state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (jid,)).fetchone()
    run = state.db.execute('SELECT * FROM gemini_runs WHERE job_id=?', (jid,)).fetchone()
    if not job or job['status'] != 'running':
        return
    stopped = False
    def signal_stop(*_):
        nonlocal stopped
        stopped = True
    if parent_pid is not None:
        signal.signal(signal.SIGTERM, signal_stop)
        signal.signal(signal.SIGINT, signal_stop)
    def check():
        row = state.db.execute('SELECT cancel FROM backend_jobs WHERE id=?', (jid,)).fetchone()
        if stopped or row['cancel'] or (parent_pid is not None and os.getppid() != parent_pid):
            raise Cancelled()
    response_path = Path(run['response_path'])
    input_path = response_path.with_suffix('.input.json')
    final_path = response_path.with_suffix('.video.json')
    try:
        config = gemini.read_config()
        if not config and client is None:
            raise ValueError('Gemini setup is missing. Open Setup Gemini.command.')
        client = client or gemini.Client(config['api_key'])
        check()
        if response_path.is_file():
            response = json.loads(response_path.read_text())
        elif run['capability'] == 'text' and json.loads(run['options_json']).get('workspace'):
            response = text_with_tools(state, job, run, client, check)
        elif run['operation_name']:
            response = {'name': run['operation_name']}
        elif run['stage'] == 'prepared':
            payload = make_request(state, job, run)
            if run['capability'] in ('text', 'image'):
                gemini.atomic_bytes(input_path, json.dumps(payload['contents'][-1]).encode())
            check()
            with state.db:
                claimed = state.db.execute("UPDATE gemini_runs SET stage='sending',attempts=attempts+1 WHERE job_id=? AND stage='prepared'", (jid,)).rowcount
            if claimed != 1:
                raise gemini.ProviderError('submission-already-claimed', uncertain=True)
            method = 'predictLongRunning' if run['capability'] == 'video' else 'generateContent'
            response = client.request('models/' + gemini.model_name(run['model']) + ':' + method, payload)
            gemini.atomic_bytes(response_path, json.dumps(response).encode())
        else:
            raise gemini.ProviderError('unconfirmed-submission', uncertain=True)
        if run['capability'] == 'video':
            operation = gemini.operation_path(response.get('name') or run['operation_name'])
            with state.db:
                state.db.execute("UPDATE gemini_runs SET stage='polling',operation_name=? WHERE job_id=?", (operation, jid))
            if final_path.is_file():
                response = json.loads(final_path.read_text())
            else:
                deadline = time.monotonic() + 3300
                errors = 0
                while True:
                    check()
                    if time.monotonic() > deadline:
                        raise gemini.ProviderError('video-poll-timeout', uncertain=True)
                    try:
                        response = client.request(operation)
                        errors = 0
                    except gemini.ProviderError as exc:
                        errors += 1
                        if errors >= 8 or exc.status in (400, 401, 403, 404):
                            raise gemini.ProviderError('video-retrieval-unavailable', uncertain=True) from None
                        sleep(min(5 * errors, 30))
                        continue
                    if response.get('done'):
                        gemini.atomic_bytes(final_path, json.dumps(response).encode())
                        break
                    sleep(10)
            if response.get('error'):
                raise ValueError('Google reported that the video operation failed. No new generation was started.')
        check()
        try:
            summary = save_outputs(state, job, run, response, client)
        except gemini.ProviderError as exc:
            if run['capability'] == 'video' and exc.status in (403, 404):
                # A refreshed GET may return a fresh download URL. Keep the
                # original operation acknowledgment; never generate again.
                final_path.unlink(missing_ok=True)
            raise
        with state.db:
            if run['capability'] in ('text', 'image'):
                state.db.execute('INSERT OR IGNORE INTO gemini_history VALUES (?,?,?,?,?,?)',
                                  (jid, job['thread_id'], run['capability'], str(input_path), str(response_path), time.time()))
            state.db.execute("UPDATE incoming SET status='submitted' WHERE id=?", (job['update_id'],))
        finish(state, jid, 'completed', summary)
    except Cancelled:
        finish(state, jid, 'stopped', 'Local work stopped. A request already sent to Google may still complete and incur usage. For a saved video operation, /resume retrieves the same result without starting another generation.')
    except gemini.ProviderError as exc:
        state.db.rollback()
        status = 'uncertain' if exc.uncertain or run['capability'] == 'video' and response_path.is_file() else 'failed'
        hint = ('Check your API key, model access, Google quota and billing.' if not exc.uncertain else 'The provider outcome is unknown. This instruction was not retried.')
        if run['capability'] == 'video':
            hint += ' If an operation was saved, /resume retries retrieval without generating another video.'
        finish(state, jid, status, f'Gemini request could not finish ({exc.status}). {hint}')
    except ValueError as exc:
        state.db.rollback()
        # Only our local validated errors are exposed; never provider exception bodies.
        finish(state, jid, 'failed', str(exc) if type(exc) is ValueError else 'The saved provider result could not be decoded.')
    except Exception:
        state.db.rollback()
        finish(state, jid, 'uncertain', 'Gemini ended without a confirmed result. A saved result can be retried with /resume; no generation is automatically replayed.')


if __name__ == '__main__':
    os.umask(0o077)
    from task_relay.bridge import State
    state = State(Path(sys.argv[1]))
    try:
        run_job(state, sys.argv[2], int(sys.argv[3]))
    finally:
        state.db.close()
