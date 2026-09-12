"""Shared installation/data bindings; resolving paths never creates or moves files.

Overrides must be absolute. Existing installation defaults are retained. External
project grants remain recorded by their owning features; paths confer no access.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path

PACKAGE=Path(__file__).resolve().parent
from .host import HOST
INSTALL=PACKAGE.parent
# Only a source checkout has these two maintained markers. An installed wheel
# uses user data by default, never a writable directory inside site-packages.
CHECKOUT=(INSTALL/'source_inventory.json').is_file() and (INSTALL/'pyproject.toml').is_file()
ASSETS=PACKAGE/'assets'
OVERRIDES=('TASK_RELAY_DATA_DIR','TASK_RELAY_WORKSPACE_DIR','TASK_RELAY_GENERATED_DIR')


@dataclass(frozen=True)
class Paths:
    install: Path
    data: Path
    workspaces: Path
    generated: Path

    @property
    def state(self):return self.data/'state.sqlite'
    @property
    def runtime(self):return self.data/'orchestrator'
    @property
    def messages(self):return self.data/'messages-pilot'
    @property
    def claude_python(self):return HOST.environment_python(self.data/'claude-venv')
    @property
    def messages_icon(self):return ASSETS/'messages-icon.png'
    @property
    def menu_icon(self):return ASSETS/'menu-icon.png'

    def environment(self):
        """Resolved bindings travel with installed services and worker processes."""
        return dict(zip(OVERRIDES,map(str,(self.data,self.workspaces,self.generated))))

    def describe(self):
        return {k:str(getattr(self,k)) for k in ('install','data','state','runtime','workspaces','generated','messages','claude_python','messages_icon','menu_icon')}


def resolve(environ=None,install=INSTALL):
    env=os.environ if environ is None else environ;install=Path(install).resolve()
    def setting(name,default):
        if name not in env:return default
        value=env[name]
        if not isinstance(value,str) or not value.strip():raise ValueError(name+' must be a nonempty absolute path')
        path=Path(value).expanduser()
        if not path.is_absolute():raise ValueError(name+' must be absolute; working-directory-relative storage is unsupported')
        return path.resolve()
    data=setting(OVERRIDES[0],install/'private' if CHECKOUT or install!=INSTALL else HOST.user_data())
    legacy=data==install/'private'
    workspaces=setting(OVERRIDES[1],install/'projects' if legacy else data.with_name(data.name.lstrip('.')+'-projects'))
    generated=setting(OVERRIDES[2],install/'generated' if legacy else data.with_name(data.name.lstrip('.')+'-generated'))
    if data==install or install.is_relative_to(data):raise ValueError('Application data must not contain the installation')
    for folder in (workspaces,generated):
        if data.is_relative_to(folder) or folder.is_relative_to(data) or install.is_relative_to(folder):raise ValueError('A workspace/output root must not expose application data or installation files')
    return Paths(install,data,workspaces,generated)


PATHS=resolve()

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--field',choices=tuple(PATHS.describe()))
    args=parser.parse_args()
    print(PATHS.describe()[args.field] if args.field else json.dumps(PATHS.describe(),indent=2))


if __name__ == '__main__':
    main()
