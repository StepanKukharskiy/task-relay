#!/usr/bin/env python3
"""Emit connector definitions and directed structural compatibility, without I/O effects."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator.connector_protocol import conformance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='Optional complete JSON report')
    args=parser.parse_args();report=conformance()
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(interfaces=len(report['interfaces']),directed_port_pairs=len(report['pairs']),
        classifications=dict(Counter(p['status'] for p in report['pairs'])),
        without_parameter_wire_schema=[k for k,v in report['interfaces'].items() if v['parameters']['schema'] is None],
        without_producer_binding=[k for k,v in report['interfaces'].items() if not (v.get('admission') or {}).get('handoffs')],
        limitations=report['limitations']),indent=2))


if __name__=='__main__':main()
