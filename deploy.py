"""Development-only upload/SSH; board runtime never calls this module."""
import argparse
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'k3maker-skill/tools'))
from k3_connect import load_device, connect, execute, upload

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--upload',nargs='*')
    parser.add_argument('--command')
    args=parser.parse_args()
    cfg=load_device(ROOT.parent/'k3maker-skill/device.json')
    client=connect(cfg)
    try:
        for name in args.upload or []:
            upload(client,cfg,ROOT/name,'~/k3-workshop/projects/siliconfly-shenzhen/'+name)
            print('Uploaded',name,flush=True)
        if args.command:
            import json
            print(json.dumps(execute(client,args.command,timeout=180),ensure_ascii=False))
    finally: client.close()
