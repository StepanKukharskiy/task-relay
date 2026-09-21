"""Opt-in local renderer qualification. No providers, downloads or messages.

Use --paths with a private JSON object of exact installed runtime paths.
Only a successful fixture render records the qualified runtime in Relay data.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import math
import struct
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_relay import media_host
from orchestrator import reel_contract,reel_document
from orchestrator.workers import atomic


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paths',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();folder=args.output.resolve();folder.mkdir(parents=True)
    runtime=media_host.identity(json.loads(args.paths.read_text()))
    from PIL import Image,ImageDraw
    im=Image.new('RGB',(320,160),'#c9dcbe');draw=ImageDraw.Draw(im)
    draw.rectangle((0,0,319,159),outline='#102030',width=8)
    draw.rectangle((8,8,70,70),fill='#c84d45');draw.rectangle((249,89,311,151),fill='#487eaa')
    im.save(folder/'source.png')
    with wave.open(str(folder/'tone.wav'),'wb') as sound:
        sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(22050)
        sound.writeframes(b''.join(struct.pack('<h',int(700*math.sin(2*math.pi*220*i/22050))) for i in range(44100)))
    value=dict(version=1,width=320,height=568,fps=15,background='#102030',foreground='#ffffff',accent='#82cfff',audio='tone.wav',
        scenes=[dict(duration=1,title='Relay',body='',image='source.png',entrance='up',narration=''),
                dict(duration=1,title='Render',body='',image=None,entrance='left',narration='')])
    reel_contract.validate(value,{'source.png':'image/png','tone.wav':'audio/wav'});atomic(folder/'composition.json',value)
    out=folder/'delivery';out.mkdir()
    try:
        checks=reel_document.render(value,folder,folder/'work',out,runtime,180,10000000)
        if media_host.identity(runtime['paths'])!=runtime:raise ValueError('Runtime changed during qualification')
    except Exception as exc:
        atomic(folder/'qualification.json',dict(qualified=False,error=str(exc),runtime=runtime));raise
    result=dict(qualified=True,runtime=runtime,implementation=media_host.implementation(),fixture=checks,recorded_at=time.time(),
        evidence=str(folder/'qualification.json'),scope='Controlled two-scene local render with image and supplied WAV; no provider or user-production qualification.')
    atomic(folder/'qualification.json',result)
    atomic(media_host.config_path(),result)
    print('Local renderer qualified. Receipt: '+str(folder/'qualification.json'))


if __name__=='__main__':main()
