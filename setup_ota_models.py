"""Fetch a bounded, pinned set of missing official SKY130 passive/LOD includes."""
import hashlib
import json
import posixpath
import re
import urllib.request
from pathlib import Path

REPOSITORY='google/skywater-pdk-libs-sky130_fd_pr'
REVISION='f62031a1be9aefe902d6d54cddd6f59b57627436'
ROOT=Path(__file__).resolve().parent/'tools/models/sky130-passives'


def run():
    ROOT.mkdir(parents=True,exist_ok=True);seen={}
    def fetch(name):
        name=posixpath.normpath(name)
        if name.startswith('../') or name.startswith('/'):raise ValueError('Include escaped repository')
        if name in seen:return
        if len(seen)>=100:raise ValueError('Include count exceeds cap')
        url=f'https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{name}'
        with urllib.request.urlopen(url,timeout=30) as response:data=response.read(500001)
        if len(data)>500000:raise ValueError('Model file exceeds byte cap')
        seen[name]=hashlib.sha256(data).hexdigest()
        dest=ROOT/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        for include in re.findall(r'^\s*\.include\s+["\']?([^"\'\s]+)',data.decode(),re.M|re.I):
            fetch(posixpath.join(posixpath.dirname(name),include))
    for name in ('models/r+c/res_typical__cap_typical.spice','models/r+c/res_typical__cap_typical__lin.spice',
                 'models/parameters/lod.spice','LICENSE'):fetch(name)
    (ROOT/'provenance.json').write_text(json.dumps(dict(repository=REPOSITORY,revision=REVISION,files_sha256=seen),indent=2)+'\n')
    print('Pinned official supplementary model files:',len(seen))


if __name__=='__main__':run()
