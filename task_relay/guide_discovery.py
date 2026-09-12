"""Topic-neutral, bounded discovery. Matches are suggestions, never permission."""
import os
from pathlib import Path
import re
import time

from task_relay.file_tools import Workspace, excluded

STOP = set('a an and are as at be by can could do file files find for from guide guides guidelines i in is it make me my of on or our please project relevant should task that the this to use using want we with work write create draft update'.split())
MARKERS = {'guide','guidelines','playbook','style','instructions','skill','conventions','standards','handbook'}


def words(text):
    return {w.rstrip('s') if len(w)>4 else w for w in re.findall(r'[^\W_]+',text.casefold()) if len(w)>2 and w not in STOP}


def discover(project,prompt,state=None):
    root=Path(project).resolve()
    if root in (Path('/'),Path.home(),Path.home()/'Documents'):
        raise ValueError('Choose a specific project folder for guide discovery.')
    workspace=Workspace(root);query=words(prompt);found=[];entries=0
    budget={'bytes':0,'incomplete':False};warnings=[]
    # Walk deterministically and disclose incomplete scans. Cached locations are
    # not trusted as current content or as approval for another task.
    for base,dirs,files in os.walk(root,followlinks=False):
        folder=Path(base);relative=folder.relative_to(root)
        entries+=len(dirs)+len(files)
        if entries>5000:
            warnings.append('The 5,000-entry search limit was reached.');break
        dirs[:]=sorted(d for d in dirs if not excluded(d) and d.casefold() not in
            ('outputs','production','dist','build','archive','archives') and not (folder/d).is_symlink())
        if len(relative.parts)>=8:
            if dirs:warnings.append('Some folders exceed the search depth limit.')
            dirs[:]=[]
        for name in sorted(files):
            path=folder/name;rel=str(path.relative_to(root))
            if name.casefold()=='agents.md' or excluded(name) or path.suffix.casefold() not in ('.md','.txt','.rst'):
                continue
            # Both named guides and documents in a guides/skills folder qualify.
            labels=set(re.findall(r'[^\W_]+',rel.casefold()))
            if not labels & (MARKERS|{'guides','skills','styles'}):continue
            try:body,_=workspace.read_text(rel,budget)
            except (OSError,ValueError):
                warnings.append('Some candidate guides could not be read within the search limits.');continue
            title=next((line.lstrip('# ').strip() for line in body.splitlines() if line.startswith('#')),name)[:160]
            path_matches=query & words(rel+' '+title)
            body_matches=query & words(body[:24000])
            # A path/title match is strong evidence; content-only matches need
            # two distinct task terms. Generic root style guidance is offered too.
            general=len(Path(rel).parts)==1 and bool(labels & {'style','conventions','standards','guidelines'})
            if not path_matches and len(body_matches)<2 and not general:continue
            score=4*len(path_matches)+len(body_matches)
            found.append(dict(source=str(path),name=rel,title=title,score=score))
    found.sort(key=lambda d:(-d['score'],d['name']))
    if len(found)>6:warnings.append(f'Found {len(found)} candidates; showing the six strongest matches.')
    found=found[:6]
    if state:
        for d in found:
            state.db.execute('''INSERT INTO project_guide_profiles VALUES (?,?,?,?,?)
                ON CONFLICT(project,purpose) DO UPDATE SET folder=excluded.folder,last_checked=excluded.last_checked''',
                (str(root),'guide:'+d['name'],str(Path(d['name']).parent),time.time(),time.time()))
    return {'guides':found,'warnings':sorted(set(warnings))}
