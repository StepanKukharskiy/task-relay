"""Create an editable PPTX locally from a bounded slide specification."""
import argparse
import hashlib
import json
from pathlib import Path

from orchestrator import pptx_document
from orchestrator.runtime import safe_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('schema', help='Show the supported slide specification')
    commands.add_parser('templates', help='Show reusable slide layouts and their content slots')
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
