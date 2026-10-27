"""Bounded check fragments for a code-assembled, exact-version review report."""
import copy,hashlib,json
from . import contracts as c
from .workers import atomic


def supported(frozen):
    from .executors import FILE_TYPES,CODE_TYPES
    from .record_recovery import supports
    return (bool(frozen.get('review_of')) and frozen.get('report_contract',{}).get('version') in (2,3)
            and frozen.get('backend',{}).get('type') in (*FILE_TYPES,*CODE_TYPES)
            and not any(frozen.get(k) for k in ('browser','computer','execution'))
            and (not frozen.get('operation_contract') or supports(frozen,'resumable')))


def tool(frozen):
    checks=frozen['report_contract']['schema']['properties']['checks']['properties']
    return dict(name='report_check',description='Save one bounded independent check judgment. value_json encodes exactly passed and evidence (or null for an unchecked blocked report). Code validates and stores it against the frozen criterion. At finish checks may be {} to select saved provisional fragments; explicit final checks amend them. Every required check and decision rule still applies.',
        parameters=dict(type='object',properties=dict(check=dict(type='string',enum=list(checks)),value_json=dict(type='string')),required=['check','value_json']))


class Store:
    def __init__(self,frozen,control):
        self.frozen=frozen;self.path=control/'report-checks.json'
        self.identity=c.digest({k:frozen.get(k) for k in ('assignment_id','review_target','inputs','criteria','report_contract')})
        self.checks={}
        if self.path.exists():
            raw=json.loads(self.path.read_text())
            if raw['identity']!=self.identity:raise ValueError('Report checkpoint changed candidate or criteria')
            for key,value in raw['checks'].items():self.validate(key,value)
            self.checks=raw['checks']

    def validate(self,key,value):
        from task_relay.planning_contract import validate
        schema=self.frozen['report_contract']['schema']['properties']['checks']['properties'].get(key)
        if schema is None:raise ValueError('Unknown frozen report check')
        validate(value,schema)

    def submit(self,args):
        if set(args)!={'check','value_json'} or not isinstance(args['value_json'],str) or len(args['value_json'].encode())>16000:
            raise ValueError('Report fragment requires one bounded check JSON value')
        value=json.loads(args['value_json']);self.validate(args['check'],value)
        checks={**self.checks,args['check']:value};data=dict(identity=self.identity,checks=checks)
        if len(c.encoded(data).encode())>min(100000,self.frozen['limits']['output_bytes']):raise ValueError('Report checkpoint exceeds frozen output allowance')
        atomic(self.path,data);self.checks=checks
        return dict(check=args['check'],saved_checks=list(checks),sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),accepted=False)

    def merge(self,report):
        if not isinstance(report,dict) or not isinstance(report.get('checks'),dict):return report
        value=copy.deepcopy(report)
        # Final explicit judgments supersede provisional fragments. Validate
        # replacements without mutating checkpoints; failed finalization cannot
        # partially publish a new judgment. Raw submissions remain in journals.
        for key,detail in value['checks'].items():self.validate(key,detail)
        value['checks']={**self.checks,**value['checks']}
        return value
