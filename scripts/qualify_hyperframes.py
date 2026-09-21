"""Controlled authored-project preview/render qualification; no model calls."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_relay import media_host
from orchestrator import hyperframes_contract as contract,hyperframes_project as project
from orchestrator.runtime import file_hash
from orchestrator.workers import atomic


def fixture():
    # Three independently animated layers and separate CSS/JS: no scene template.
    return dict(version=1,width=320,height=568,fps=15,duration=2,audio=False,samples=[.4,1.6],assets={},files={
        'index.html':'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head><body>'
        '<main id="reel" data-composition-id="reel" data-width="320" data-height="568" data-duration="2" data-no-timeline>'
        '<div id="background"></div><div id="card"><h1>Full project</h1><p>Independent motion.</p></div>'
        '<div id="character"></div></main><script src="motion.js"></script></body></html>',
        'style.css':'@font-face{font-family:Relay;src:url(assets/relay-font.ttf)}*{box-sizing:border-box}'
        'html,body,#reel{width:100%;height:100%;margin:0;overflow:hidden}#reel{position:relative;background:#182838;color:white;font-family:Relay}'
        '#background{position:absolute;inset:0;background:linear-gradient(135deg,#182838,#425e61)}'
        '#card{position:absolute;left:24px;top:160px;width:272px;padding:20px;background:#ffffff18;border:1px solid #ffffff60;border-radius:20px;backdrop-filter:blur(12px)}'
        'h1{font-size:26px;margin:0 0 14px}p{font-size:18px;margin:0}#character{position:absolute;left:140px;bottom:70px;width:40px;height:80px;border-radius:20px;background:#b8f0d5}',
        'motion.js':'document.addEventListener("DOMContentLoaded",()=>{document.getElementById("background").animate([{transform:"scale(1)"},{transform:"scale(1.04)"}],{duration:2000,fill:"both"}).pause();'
        'document.getElementById("card").animate([{transform:"translateX(-36px)",opacity:0},{transform:"translateX(0)",opacity:1}],{duration:300,fill:"both"}).pause();'
        'document.getElementById("character").animate([{transform:"translateY(40px)"},{transform:"translateY(0px)"}],{delay:300,duration:800,fill:"both"}).pause();});'})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--paths',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();root=args.output.resolve();root.mkdir(parents=True)
    runtime=media_host.identity(json.loads(args.paths.read_text()));value=contract.validate(fixture(),{})
    preview=root/'preview';preview.mkdir();work=root/'preview-work';work.mkdir();source=work/'source'
    try:
        project.materialize(value,root,source,runtime);atomic(preview/'project.json',value);project.archive(source,preview/'project.zip')
        checks=project.run_project(value,source,work,preview,runtime,180,20000000)
        checks['project_sha256']=file_hash(preview/'project.zip')
        receipt=dict(capability='hyperframes.preview',passed=True,selected=False,runtime=runtime,implementation=media_host.implementation(),checks=checks)
        atomic(preview/'verification.json',receipt)
        out=root/'render';out.mkdir();work=root/'render-work';work.mkdir()
        restored=project.restore(preview/'project.zip',receipt,work/'source')
        encoded=project.run_project(restored,work/'source',work,out,runtime,180,20000000,render=True)
        if media_host.identity(runtime['paths'])!=runtime:raise ValueError('Runtime changed during qualification')
    except Exception as exc:
        atomic(root/'qualification.json',dict(qualified=False,error=str(exc)));raise
    result=dict(qualified=True,project_qualified=True,runtime=runtime,implementation=media_host.implementation(),
        fixture={'preview':checks,'render':encoded},recorded_at=time.time(),evidence=str(root/'qualification.json'),
        scope='Controlled authored HTML/CSS/JS preview and exact-bundle rendering; not a provider call or user-content approval.')
    atomic(root/'qualification.json',result);atomic(media_host.config_path(),result)
    print('Full-project preview and rendering qualified: '+str(root/'qualification.json'))


if __name__=='__main__':main()
