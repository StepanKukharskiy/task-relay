"""Run the complete controlled browser gate and retain its report/artifacts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
SUITES=['tests.test_browser_pipeline','tests.test_browser_requests','tests.test_general_browser','tests.test_browser_executor',
        'tests.test_browser_jobs','tests.test_browser_setup','tests.test_perplexity_browser']


def run_tests():
    import unittest
    output=Path(os.environ['RELAY_BROWSER_PIPELINE_OUTPUT']);cases=[]
    class Recorded(unittest.TextTestResult):
        def startTest(self,test):
            super().startTest(test);self.started=time.monotonic()
            self.case={'test':test.id(),'status':'running'};cases.append(self.case);self.save()
        def save(self):(output/'cases.json').write_text(json.dumps(cases,indent=2))
        def addSuccess(self,test):super().addSuccess(test);self.case['status']='passed'
        def addFailure(self,test,err):
            super().addFailure(test,err);self.case.update(status='failed',detail=self._exc_info_to_string(err,test))
        def addError(self,test,err):
            super().addError(test,err);self.case.update(status='error',detail=self._exc_info_to_string(err,test))
        def addSkip(self,test,reason):super().addSkip(test,reason);self.case.update(status='skipped',detail=reason)
        def stopTest(self,test):
            self.case['seconds']=round(time.monotonic()-self.started,3);self.save();super().stopTest(test)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Recorded).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'outputs/browser-pipeline'/time.strftime('%Y%m%d-%H%M%S'))
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'TASK_RELAY_LOCAL_BROWSER_FIXTURE':'1','RELAY_BROWSER_PIPELINE_OUTPUT':str(out)}
    command=[sys.executable,'-c','from scripts.test_browser_pipeline import run_tests; run_tests()']
    print('Running real Chromium, CLI and supervised workers with a scripted model transport. Evidence: '+str(out),flush=True)
    start=time.time()
    with (out/'tests.log').open('w') as log:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    report={'command':command,'returncode':result.returncode,'elapsed_seconds':round(time.time()-start,2),
            'passed':result.returncode==0,'scope':'Real local Chromium and normal CLI/supervisor/worker code; model transport and Perplexity DOM are controlled fixtures. No live accounts, paid generation or message delivery.'}
    cases=json.loads((out/'cases.json').read_text()) if (out/'cases.json').exists() else []
    report.update(tests=len(cases),failures=[case['test'] for case in cases if case['status']!='passed'],suites=SUITES)
    (out/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));print((out/'tests.log').read_text()[-5000:])
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
