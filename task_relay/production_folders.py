"""Human-editable research folders linked to registered productions."""
import hashlib
import json
from pathlib import Path
import secrets


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS production_folders (run TEXT PRIMARY KEY, path TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS production_folder_files (
      run TEXT NOT NULL, relative TEXT NOT NULL, sha256 TEXT NOT NULL, input_id INTEGER NOT NULL,
      PRIMARY KEY(run,relative));
    ''')


def base_folder():
    return Path.home() / 'Documents' / 'Task Relay Productions'


def checked_directory(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError('The production folder must not contain symbolic links: ' + str(p))
    if path.exists() and not path.is_dir():
        raise ValueError('A file occupies the production folder path: ' + str(path))
    return path


def source_run(state, run):
    """A successor keeps the user's existing research folder and ownership marker."""
    seen=set()
    while not state.db.execute('SELECT 1 FROM production_folders WHERE run=?',(run,)).fetchone():
        if run in seen or len(seen)>=20:
            raise ValueError('Invalid production research lineage.')
        seen.add(run)
        row=state.db.execute('SELECT parent FROM production_continuations WHERE child=?',(run,)).fetchone()
        if not row:break
        run=row['parent']
    return run


def folder(state, run):
    run=source_run(state,run)
    row = state.db.execute('SELECT path FROM production_folders WHERE run=?', (run,)).fetchone()
    if not row:
        return None
    path = checked_directory(row[0])
    marker = path / '.relay-production.json'
    from orchestrator.runtime import safe_file
    if json.loads(safe_file(path, marker.name).read_text()).get('run') != run:
        raise ValueError('The production folder link changed.')
    checked_directory(path / 'research')
    return path


def view(state, run):
    row = state.db.execute('SELECT path FROM production_folders WHERE run=?', (source_run(state,run),)).fetchone()
    if not row:
        return None
    return {'path':row[0], 'research_path':str(Path(row[0])/'research'),
            'imported_files':state.db.execute('SELECT count(*) FROM production_folder_files WHERE run=?',(run,)).fetchone()[0],
            'policy':'User files are imported as immutable copies on request or with a revision. This folder is not watched; saving a file does not launch work.'}


def create(state, run):
    from task_relay import production_control as pc
    from orchestrator.contracts import label
    label(run)
    if not any(v['name']==run for v in pc.inspect(state)):
        raise ValueError('Choose a registered production before creating its research folder.')
    existing = folder(state,run)
    if existing:
        return 'Production folder already exists:\n' + str(existing) + '\nPut research in:\n' + str(existing/'research')
    base = checked_directory(base_folder())
    path = checked_directory(base / run)
    marker = path / '.relay-production.json'
    if path.exists():
        from orchestrator.runtime import safe_file
        try:
            owned = json.loads(safe_file(path,marker.name).read_text()).get('run') == run
        except (OSError,ValueError):
            owned = False
        if not owned:
            raise ValueError('That folder already exists and is not linked to this production. Existing files were not changed.')
    else:
        base.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.mkdir(mode=0o700)
        with marker.open('x') as out:
            json.dump({'run':run,'purpose':'User research for this production'},out,indent=2)
    research=checked_directory(path/'research');research.mkdir(exist_ok=True,mode=0o700)
    readme=path/'README.md'
    if not readme.exists():
        with readme.open('x') as out:
            out.write(f'''# {run}

Place your research in `research/`: notes, saved pages, PDFs, screenshots or other source files.
For online claims, include the source URL and the date you checked it in your notes.

Reply to this production in Telegram: “Import the research from my folder.”
The relay copies new/changed files into its immutable input store. You can also
request a preparation revision; the linked research is imported before its card.
Each import allows at most ten new files, 20 MB each and 50 MB total, including
pending Telegram guides. Subfolders are supported; hidden files are ignored.

Saving files here does not start work. Imports do not launch research, consume
worker attempts, or change a stage's scope. Apply a revision card to send the
registered inputs to preparation and independent review, when attempts remain.
The worker's registered copies do not change when you edit these local originals.
''')
    state.db.execute('INSERT OR IGNORE INTO production_folders(run,path) VALUES (?,?)',(run,str(path)))
    return ('Production folder created:\n'+str(path)+'\n\nPut your research in:\n'+str(research)+
            '\n\nWhen ready, reply “Import the research from my folder.” Files are copied into the production inputs; saving them here does not start work.')


def import_research(state, run):
    from task_relay.codex_inputs import MAX_FILE, MAX_COUNT, MAX_TOTAL
    from orchestrator.runtime import safe_file
    from task_relay import production_control as pc
    path=folder(state,run)
    if path is None:
        raise ValueError('Create this production’s research folder first.')
    research=path/'research'
    # Refuse incomplete collections rather than quietly dropping non-hidden files.
    candidates=[]; entries=0
    def walk(directory):
        nonlocal entries
        for p in sorted(directory.iterdir()):
            entries+=1
            if entries>500:
                raise ValueError('Research folder is too large to import at once (500 entries).')
            if p.name.startswith('.'):
                continue
            if p.is_symlink():
                raise ValueError('Research symlinks cannot be imported: '+str(p.relative_to(research)))
            if p.is_dir():
                if len(p.relative_to(research).parts)>8:
                    raise ValueError('Research folder nesting exceeds eight levels.')
                walk(p)
            else:
                candidates.append(p)
    walk(research)
    pending=[];total=0
    for source in candidates:
        relative=str(source.relative_to(research))
        source=safe_file(research,relative)
        before=source.stat()
        if before.st_size>MAX_FILE:
            raise ValueError('Research file exceeds 20 MB: '+relative)
        with source.open('rb') as inp:data=inp.read(MAX_FILE+1)
        after=source.stat()
        if not data or len(data)>MAX_FILE or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
            raise ValueError('Research file is empty or changed during import: '+relative)
        digest=hashlib.sha256(data).hexdigest()
        old=state.db.execute('SELECT * FROM production_folder_files WHERE run=? AND relative=?',(run,relative)).fetchone()
        if old and old['sha256']==digest:
            continue
        total+=len(data)
        if len(pending)>=MAX_COUNT or total>MAX_TOTAL:
            raise ValueError('Import at most ten new/changed research files and 50 MB at a time.')
        pending.append((source,relative,data,digest,old))
    replaced={p[4]['input_id'] for p in pending if p[4]}
    ready=state.db.execute("SELECT id,COALESCE(bytes,declared_size) size FROM production_uploads WHERE run=? AND status IN ('pending','ready')",(run,)).fetchall()
    retained=[r for r in ready if r['id'] not in replaced]
    if len(retained)+len(pending)>MAX_COUNT or sum(r['size'] for r in retained)+total>MAX_TOTAL:
        raise ValueError('Research and pending Telegram guides exceed ten files or 50 MB. Import fewer files.')
    for source,relative,data,digest,old in pending:
        token=-secrets.randbits(62)-1
        # Telegram IDs are positive; local immutable snapshots have distinct negative IDs.
        filename=source.name
        destination=pc.root(state).parent/'production-guides'/str(token)/filename
        destination.parent.mkdir(parents=True,mode=0o700)
        with destination.open('xb') as out:out.write(data)
        destination.chmod(0o400)
        state.db.execute("INSERT INTO production_uploads(id,run,file_id,filename,caption,declared_size,status,path,sha256,bytes) VALUES (?,?,?,?,?,?,'ready',?,?,?)",
            (token,run,'local-research',filename,'User research: '+relative+'; imported from '+str(source),len(data),str(destination.resolve()),digest,len(data)))
        if old:
            state.db.execute("UPDATE production_uploads SET status='replaced' WHERE id=? AND status='ready'",(old['input_id'],))
        state.db.execute('INSERT OR REPLACE INTO production_folder_files VALUES (?,?,?,?)',(run,relative,digest,token))
    return (f'Imported {len(pending)} new/changed research file(s) for {run}.\n'+
            ('\n'.join(p[1] for p in pending)+'\n' if pending else '')+
            'Original files remain in your research folder. No worker was launched. Ask for a preparation revision when ready; existing stage limits still apply.')
