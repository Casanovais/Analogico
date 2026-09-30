"""Bounded, revision-pinned ZIP/ZIP64 inventory and text sampling; no execution."""
import argparse
import hashlib
import json
import struct
import urllib.request
import zlib
from pathlib import Path


def audit(output):
    output.mkdir(parents=True,exist_ok=True)
    meta=json.load(urllib.request.urlopen('https://huggingface.co/api/datasets/hardware-fab/osiris',timeout=30))
    revision=meta['sha']
    (output/'metadata.json').write_text(json.dumps(meta,indent=2))
    tree=json.load(urllib.request.urlopen(f'https://huggingface.co/api/datasets/hardware-fab/osiris/tree/{revision}',timeout=30))
    for entry in tree:
        name=entry['path']
        if not name.endswith('.zip'): continue
        total=entry['size']
        url=f'https://huggingface.co/datasets/hardware-fab/osiris/resolve/{revision}/{name}'
        transferred=0
        def fetch(start,end):
            nonlocal transferred
            if not 0<=start<=end<total or end-start+1>64*1024*1024:
                raise ValueError('Range exceeds 64 MiB audit limit')
            request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(request,timeout=60) as response:
                expected=f'bytes {start}-{end}/{total}'
                if response.status!=206 or response.headers.get('Content-Range')!=expected:
                    raise RuntimeError('Server failed to honor exact bounded range')
                data=response.read(end-start+2)
                if len(data)!=end-start+1: raise RuntimeError('Range size mismatch')
                transferred+=len(data)
                return data
        tail=fetch(total-65536,total-1)
        pos=tail.rfind(b'PK\x05\x06')
        if pos<0: raise ValueError('No EOCD found')
        eocd=struct.unpack('<4s4H2IH',tail[pos:pos+22])
        size,offset=eocd[5:7]
        if size==0xffffffff or offset==0xffffffff:
            zpos=tail.rfind(b'PK\x06\x06')
            if zpos<0: raise ValueError('ZIP64 record outside bounded tail')
            record=struct.unpack('<4sQ2H2I4Q',tail[zpos:zpos+56])
            size,offset=record[8:10]
        print(name, 'central directory bytes',size,'offset',offset,flush=True)
        if size>64*1024*1024:
            (output/(name+'.status.json')).write_text(json.dumps(dict(status='Directory exceeds bounded audit cap',central_directory_bytes=size,offset=offset)))
        central=fetch(offset,offset+min(size,1024*1024)-1) if size>64*1024*1024 else fetch(offset,offset+size-1)
        inventory=[]; cursor=0; samples=[]
        while cursor+46<=len(central):
            fields=struct.unpack('<4s6H3I5H2I',central[cursor:cursor+46])
            if fields[0]!=b'PK\x01\x02': raise ValueError('Invalid central directory')
            namelen,extralen,commentlen=fields[10:13]
            if cursor+46+namelen+extralen+commentlen>len(central): break
            filename=central[cursor+46:cursor+46+namelen].decode('utf-8')
            compressed,uncompressed,local=fields[8],fields[9],fields[16]
            item=dict(path=filename,size=uncompressed,compressed_size=compressed,local_offset=local,method=fields[4])
            inventory.append(item)
            lower=filename.lower()
            if (lower.endswith('.json') and name=='Osiris_Dataset.zip' and len(samples)<5) or (lower.endswith('/license') or lower.endswith('/osiris.py') or lower.endswith('/config.py')) and '_internal' not in lower:
                samples.append(item)
            cursor+=46+namelen+extralen+commentlen
        (output/(name+'.inventory.json')).write_text(json.dumps(inventory,indent=2))
        # Only explicitly selected small text files, never executable archives.
        for item in samples[:5]:
            if item['size']>100000 or item['compressed_size']>100000 or item['local_offset']==0xffffffff: continue
            header=fetch(item['local_offset'],item['local_offset']+29)
            local_fields=struct.unpack('<4s5H3I2H',header)
            if local_fields[0]!=b'PK\x03\x04': raise ValueError('Invalid local header')
            start=item['local_offset']+30+local_fields[-2]+local_fields[-1]
            data=fetch(start,start+item['compressed_size']-1)
            if item['method']==8:
                decoder=zlib.decompressobj(-15)
                text=decoder.decompress(data,100001)
                if decoder.unconsumed_tail or not decoder.eof: raise ValueError('Invalid or excessive decompressed sample')
            elif item['method']==0: text=data
            else: continue
            if len(text)!=item['size']: raise ValueError('Uncompressed size mismatch')
            dest=output/'samples'/name/Path(item['path']).name
            dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(text)
        print(name, 'entries',len(inventory),'bytes downloaded',transferred,flush=True)
    files={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file() and p.name!='audit.json'}
    (output/'audit.json').write_text(json.dumps(dict(revision=revision,files_sha256=files,
        status='Inventory and selected text only; external data not admitted to training'),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    audit(p.parse_args().output)
