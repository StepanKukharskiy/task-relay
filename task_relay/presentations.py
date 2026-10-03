"""Create an editable PPTX locally from a bounded slide specification."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from orchestrator import pptx_document, pptx_edit
from orchestrator.runtime import safe_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('schema', help='Show the supported slide specification')
    commands.add_parser('edit-schema', help='Show the guarded existing-PPTX edit manifest')
    commands.add_parser('templates', help='Show reusable slide layouts and their content slots')
    inspect = commands.add_parser('inspect', help='List slide shape IDs and exact editable text runs')
    inspect.add_argument('presentation', type=Path)
    edit = commands.add_parser('edit', help='Apply guarded edits to an exact existing PPTX')
    edit.add_argument('presentation', type=Path)
    edit.add_argument('manifest', type=Path)
    edit.add_argument('--image', action='append', default=[], help='Exact replacement PNG/JPEG path relative to the manifest; repeat as needed')
    edit.add_argument('--output-dir', type=Path, required=True, help='New candidate directory')
    create = commands.add_parser('create')
    create.add_argument('specification', type=Path)
    create.add_argument('--image', action='append', default=[], help='Declared relative image path, resolved beside the specification; repeat as needed')
    create.add_argument('--image-bundle', action='append', default=[], help='Exact images.collect ZIP beside the specification; repeat as needed')
    create.add_argument('--output-dir', type=Path, required=True, help='New directory; existing output directories are never overwritten')
    args = parser.parse_args(argv)
    if args.command == 'schema':
        print(pptx_document.DESCRIPTION)
        return 0
    if args.command == 'templates':
        from orchestrator.slide_templates import CATALOG, COLLECTION_LAYOUTS, STYLES
        print(json.dumps(dict(layouts=CATALOG,collections=COLLECTION_LAYOUTS,styles=STYLES),indent=2))
        return 0
    if args.command == 'edit-schema':
        print(pptx_edit.DESCRIPTION)
        return 0
    if args.command == 'inspect':
        try:
            print(json.dumps(pptx_edit.inspect(args.presentation.read_bytes()), ensure_ascii=False, indent=2))
            return 0
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            print('Presentation inspection failed: '+str(exc))
            return 1
    if args.command == 'edit':
        try:
            if args.presentation.is_symlink() or args.manifest.is_symlink():
                raise ValueError('PPTX and manifest must not be symlinks.')
            if args.manifest.stat().st_size > 1000000:
                raise ValueError('PPTX edit manifest exceeds 1 MB.')
            baseline=args.presentation.read_bytes();source=args.manifest.read_bytes()
            if len(args.image)>18 or len(set(args.image))!=len(args.image):
                raise ValueError('Use at most 18 distinct replacement pictures.')
            images={};input_receipts=[]
            for name in args.image:
                path=safe_file(args.manifest.resolve().parent,name)
                images[name]=path.read_bytes()
                input_receipts.append({'path':name,'sha256':hashlib.sha256(images[name]).hexdigest()})
            if len(baseline)+len(source)+sum(map(len,images.values()))>51000000:
                raise ValueError('PPTX edit inputs exceed 51 MB.')
            data,evidence=pptx_edit.edit(baseline,pptx_edit.load(source.decode('utf-8')),images=images)
            args.output_dir.mkdir(parents=True,exist_ok=False)
            target=args.output_dir/'presentation.pptx'
            with target.open('xb') as stream:stream.write(data)
            receipt={'execution':{'capability':'pptx.edit','version':1,'parameters':{}},'outcome':'completed',
                     'inputs':[{'path':str(args.presentation),'sha256':hashlib.sha256(baseline).hexdigest()},
                               {'path':str(args.manifest),'sha256':hashlib.sha256(source).hexdigest()},*input_receipts],
                     'output_sha256':hashlib.sha256(data).hexdigest(),'output_bytes':len(data),'validation':evidence}
            with (args.output_dir/'receipt.json').open('x') as stream:json.dump(receipt,stream,indent=2)
            print(json.dumps({'output':str(target),**receipt}))
            return 0
        except (ValueError,OSError,UnicodeError,zipfile.BadZipFile) as exc:
            print('Presentation editing failed: '+str(exc))
            return 1
    try:
        if args.specification.is_symlink():
            raise ValueError('Slide specification must not be a symlink.')
        if args.specification.stat().st_size > 2000000:
            raise ValueError('Slide specification exceeds 2 MB.')
        source = args.specification.read_bytes()
        inputs = [{'path': args.specification.name, 'sha256': hashlib.sha256(source).hexdigest()}]
        images = {};bundles={}
        total = len(source)
        names=args.image+args.image_bundle
        if len(names) > 49 or len(names) != len(set(names)):
            raise ValueError('Use at most 49 unique declared images.')
        for name in names:
            path = safe_file(args.specification.resolve().parent, name)
            total += path.stat().st_size
            if total > 50000000:
                raise ValueError('Presentation inputs exceed 50 MB.')
            raw=path.read_bytes()
            (bundles if name in args.image_bundle else images)[name]=raw
            inputs.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest()})
        data, evidence = pptx_document.create(pptx_document.load(source.decode('utf-8')), images,bundles=bundles)
        # Reserve one candidate directory. Failure never replaces an earlier run.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        target = args.output_dir / 'presentation.pptx'
        with target.open('xb') as stream:
            stream.write(data)
        receipt = {'execution': {'capability': 'pptx.create', 'version': 1, 'parameters': {}},
                   'outcome': 'completed', 'inputs': inputs, 'output_sha256': hashlib.sha256(data).hexdigest(),
                   'output_bytes': len(data), 'validation': evidence}
        with (args.output_dir / 'receipt.json').open('x') as stream:
            json.dump(receipt, stream, indent=2)
        print(json.dumps({'output': str(target), **receipt}))
        return 0
    except (ValueError, OSError) as exc:
        print('Presentation creation failed: ' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
