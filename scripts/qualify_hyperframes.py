"""Controlled authored-project preview/render qualification; no model calls."""
import argparse
import json
import shutil
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_relay import media_host
from orchestrator import hyperframes_contract as contract,hyperframes_project as project
from orchestrator.runtime import file_hash
from orchestrator.workers import atomic


def fixture(gsap=False):
    # Three independently animated layers and separate CSS/JS: no scene template.
    value=dict(version=1,width=320,height=568,fps=15,duration=2,audio=False,samples=[.4,1.6],assets={},files={
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
    if gsap:
        value['assets']['assets/gsap.min.js']='gsap.min.js'
        value['files']['index.html']=value['files']['index.html'].replace('<meta charset="utf-8">',
            '<meta charset="utf-8"><script src="assets/gsap.min.js"></script>').replace(' data-no-timeline','').replace(
            '<script src="motion.js"></script>', '<script>'+value['files'].pop('motion.js')+'</script>')
        start=value['files']['index.html'].index('<script>')
        value['files']['index.html']=value['files']['index.html'][:start]+'''<script>
if (!window.gsap) throw new Error('Qualified local GSAP must load before authored timeline');
const timeline=gsap.timeline({paused:true});
timeline.to('#background',{scale:1.04,duration:2,ease:'none'},0);
timeline.from('#card',{x:-36,opacity:0,duration:.3},0);
timeline.from('#character',{y:40,duration:.8},.3);
window.__timelines=window.__timelines||{};window.__timelines.reel=timeline;
</script></body></html>'''
    return value


def managed_fixture(engine='gsap'):
    value=fixture(engine=='gsap');value.update(version=2,animation_runtime=engine)
    if engine=='gsap':
        value['assets']={}
        value['files']['index.html']=value['files']['index.html'].replace('<script src="assets/gsap.min.js"></script>','').replace(
            'const timeline=gsap.timeline({paused:true});','const timeline=window.relayTimeline;').replace(
            'window.__timelines=window.__timelines||{};window.__timelines.reel=timeline;','')
    return value


def qualify(value,root,runtime,inputs=None):
    root.mkdir();preview=root/'preview';preview.mkdir();work=root/'preview-work';work.mkdir();source=work/'source'
    for name,path in (inputs or {}).items():shutil.copyfile(path,root/name)
    project.materialize(value,root,source,runtime);atomic(preview/'project.json',value);project.archive(source,preview/'project.zip')
    checks=project.run_project(value,source,work,preview,runtime,180,20000000)
    checks['project_sha256']=file_hash(preview/'project.zip')
    receipt=dict(capability='hyperframes.preview',passed=True,selected=False,runtime=runtime,implementation=media_host.implementation(),checks=checks)
    atomic(preview/'verification.json',receipt)
    out=root/'render';out.mkdir();render_work=root/'render-work';render_work.mkdir()
    restored=project.restore(preview/'project.zip',receipt,render_work/'source')
    encoded=project.run_project(restored,render_work/'source',render_work,out,runtime,180,20000000,render=True)
    for folder in (work/'frames',render_work/'frames'):
        if len({file_hash(p) for p in folder.rglob('*.png')})<2:raise ValueError('Animation qualification produced no distinct sampled frames')
    if media_host.identity(runtime['paths'])!=runtime:raise ValueError('Runtime changed during qualification')
    return dict(preview=checks,render=encoded)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--paths',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gsap',type=Path,help='Also qualify a legacy project with this explicitly supplied local GSAP library')
    args=p.parse_args();root=args.output.resolve();root.mkdir(parents=True)
    runtime=media_host.identity(json.loads(args.paths.read_text()));fixtures={}
    try:
        for engine in ('gsap','waapi'):
            fixtures[engine]=qualify(contract.validate(managed_fixture(engine),{}),root/engine,runtime)
        if args.gsap:
            fixtures['legacy']=qualify(contract.validate(fixture(True),{'gsap.min.js':'text/javascript'}),
                root/'legacy',runtime,inputs={'gsap.min.js':args.gsap})
    except Exception as exc:
        atomic(root/'qualification.json',dict(qualified=False,error=str(exc)));raise
    from orchestrator import animation_runtime
    result=dict(qualified=True,project_qualified=True,runtime=runtime,implementation=media_host.implementation(),
        fixture=fixtures['gsap'],animation_fixtures=fixtures,animation_runtimes=['gsap','waapi'],
        animation_dependencies=animation_runtime.identity(),recorded_at=time.time(),evidence=str(root/'qualification.json'),
        scope='Controlled managed GSAP and WAAPI preview/exact-bundle rendering with distinct sampled frames; no model calls or user-content approval.')
    atomic(root/'qualification.json',result)
    destination=media_host.config_path();destination.parent.mkdir(parents=True,exist_ok=True);atomic(destination,result)
    print('Managed animation preview and rendering qualified: '+str(root/'qualification.json'))


if __name__=='__main__':main()
