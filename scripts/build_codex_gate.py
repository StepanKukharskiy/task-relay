#!/usr/bin/env python3
"""Build the pinned Relay-scoped Codex runtime; qualification is a separate step."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from orchestrator.codex_gate import UPSTREAM_REVISION, PATCH_SHA256


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--checkout',type=Path,required=True);parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();checkout=args.checkout.resolve()
    patch=ROOT/'runtime-patches/codex-tool-authority-v1.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest()!=PATCH_SHA256:raise ValueError('Maintained patch changed')
    if not checkout.exists():
        subprocess.run(['git','clone','--depth','1','--branch','rust-v0.162.0-alpha.17.2','https://github.com/openai/codex.git',str(checkout)],check=True)
    revision=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    if revision!=UPSTREAM_REVISION:raise ValueError('Unexpected upstream revision; checkout left unchanged')
    applied=subprocess.run(['git','-C',str(checkout),'apply','--reverse','--check',str(patch)],capture_output=True).returncode==0
    if not applied:
        subprocess.run(['git','-C',str(checkout),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-C',str(checkout),'apply',str(patch)],check=True)
    subprocess.run(['cargo','build','--locked','--manifest-path',str(checkout/'codex-rs/Cargo.toml'),
                    '-p','codex-app-server','--bin','codex-app-server','--profile','dev-small','-j',str(args.jobs)],check=True)
    print(checkout/'codex-rs/target/dev-small/codex-app-server')
    print('Run scripts/qualify_codex_gate.py for this exact binary before selecting it.')


if __name__=='__main__':main()
