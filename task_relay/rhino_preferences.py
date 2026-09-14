"""Local preferred Rhino version. Existing execution approvals remain frozen."""
import os
from .relay_paths import PATHS


def preference(paths=PATHS):
    from .credentials import private_json,CredentialError
    path=paths.data/'rhino-preference.json'
    if not path.exists():return 'auto'
    try:
        value=private_json(path)
        if set(value)!={'version','major'} or value['version']!=1 or value['major'] not in ('auto','7','8'):return 'invalid'
        return value['major']
    except CredentialError:return 'invalid'


def snapshot(paths=PATHS):
    from .host_apps import rhino
    versions=[r for major in ('7','8') if (r:=rhino({'TASK_RELAY_RHINO_VERSION':major}))['available']]
    return {'preference':preference(paths),'versions':versions,'selected':rhino(),
            'managed':bool(os.environ.get('TASK_RELAY_RHINO') or os.environ.get('TASK_RELAY_RHINO_VERSION'))}


def update(value,paths=PATHS):
    from .host_apps import rhino
    from .credentials import save
    from .onboarding import setup_lock
    if not isinstance(value,dict) or set(value)!={'major'} or value['major'] not in ('auto','7','8'):raise ValueError('Choose Auto, Rhino 7 or Rhino 8.')
    if os.environ.get('TASK_RELAY_RHINO') or os.environ.get('TASK_RELAY_RHINO_VERSION'):raise ValueError('Rhino is managed by an explicit host override. Remove that override before changing its preference.')
    if value['major']!='auto' and not rhino({'TASK_RELAY_RHINO_VERSION':value['major']})['available']:raise ValueError('That Rhino version is not installed or supported on this host.')
    with setup_lock():save(paths.data/'rhino-preference.json',dict(version=1,major=value['major']))
    return {'message':'Rhino preference saved for new plans. Existing approved code keeps its runtime; prepare a new plan to change versions.'}
