"""Read-only compatibility for local media failures missing execution identity.

Never infer success, rewrite an old receipt, or run an operation. The existing
scheduler may collect a stopped, bound failure using these original journals.
"""
import json
from pathlib import Path
from .contracts import digest
from .runtime import file_hash


def historical_failure(control, result, details):
    cap=result.get('execution',{}).get('capability')
    kind={'hyperframes.preview':'hyperframes','hyperframes.render':'hyperframes',
          'media.compose':'media'}.get(cap)
    if not kind or 'execution' in details or details.get('outcome')!='failed' or details.get('passed') is not False:
        return None
    paths=[]
    def read(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size>2000000:
            raise ValueError('Missing or invalid local receipt')
        paths.append(path)
        return json.loads(path.read_text())
    try:
        launch=read(control/'launch.json');done=read(control/'done.json')
        frozen=read(Path(launch['workspace'])/'.relay/ASSIGNMENT.json')
        dispatch=read(control/'operation-dispatch.json')
        intent=read(control/(kind+'-intent.json'))
        ident=frozen['assignment_id']
        if (launch['token']!=ident or done['token']!=ident or details['assignment']!=ident
            or launch['execution']!=result['execution'] or frozen['execution']!=result['execution']
            or dispatch['binding']!=digest(frozen) or details['capability']!=cap
            or type(done.get('exit_code')) is not int or done['exit_code']==0
            or not done.get('finished') or done.get('reason') is not None
            or not details.get('reason') or details.get('recorded_at',float('inf'))>done['finished']
            or not intent or any(details.get(k)!=v for k,v in intent.items())
            or intent['input_versions']!=[{k:i[k] for k in ('artifact','path','sha256')} for i in frozen['inputs']]
            or intent['runtime']!=frozen['media_runtime'] or intent['limits']!=frozen['limits']):
            return None
        # Every started CLI command must have a terminal guardian outcome. A
        # missing outcome or guardian cleanup error remains uncertain.
        guards=sorted((control/(kind+'-work')).glob('command-*/guard.json'))
        if not guards:return None
        codes=[]
        for guard in guards:
            outcome=read(guard.with_name('outcome.json'))
            if set(outcome)!={'returncode'} or type(outcome['returncode']) is not int:return None
            codes.append(outcome['returncode'])
        if not any(codes):return None
        paths.append(control/'operation.json')
        return dict(kind='confirmed_local_media_failure',replayed=False,
                    assignment=ident,binding=dispatch['binding'],
                    evidence={str(p):file_hash(p) for p in paths})
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return None
