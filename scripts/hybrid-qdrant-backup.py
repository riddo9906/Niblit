"""Create/download Qdrant v1.18 collection snapshots; never restore or delete."""
import argparse,hashlib,json,shutil,time
from pathlib import Path
from urllib.parse import quote
import httpx
from dotenv import dotenv_values

def backup(config, directory, resume_latest=False):
    values=dotenv_values(config);key=values.get('QDRANT_API_KEY')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(directory).free<4*1024**3:raise RuntimeError('At least 4 GiB free required before collection snapshots')
    results=[]
    with httpx.Client(base_url='http://127.0.0.1:6333',headers={'api-key':key} if key else {},trust_env=False,
                      timeout=60,limits=httpx.Limits(max_keepalive_connections=0)) as client:
        response=client.get('/collections');response.raise_for_status()
        for collection in response.json()['result']['collections']:
            name=collection['name'];path='/collections/'+quote(name,safe='')
            completed=[]
            for manifest in directory.glob('*.manifest.json'):
                receipt=json.loads(manifest.read_text(encoding='utf-8'))
                if receipt.get('collection')==name:
                    saved=Path(receipt['snapshot'])
                    if not saved.is_file() or hashlib.sha256(saved.read_bytes()).hexdigest()!=receipt['sha256']:
                        raise ValueError('Previously saved snapshot checksum failed')
                    completed.append(receipt)
            if completed:
                results.append(max(completed,key=lambda r:r['created_at']));continue
            info=client.get(path);info.raise_for_status()
            snapshot=None
            if resume_latest:
                listed=client.get(path+'/snapshots');listed.raise_for_status()
                if listed.json()['result']:snapshot=max(listed.json()['result'],key=lambda s:s['creation_time'])
            if snapshot is None:
                created=client.post(path+'/snapshots',params={'wait':'true'});created.raise_for_status()
                snapshot=created.json()['result']
            filename=snapshot['name']
            if Path(filename).name!=filename or '..' in filename:raise ValueError('Unsafe snapshot filename')
            if snapshot['size']>2*1024**3:raise RuntimeError('Snapshot exceeds bounded download; source snapshot retained, no repeat attempted')
            target=directory/filename
            if target.exists():raise FileExistsError('Existing snapshot must not be overwritten')
            partial=target.with_suffix('.partial');digest=hashlib.sha256();size=0
            with client.stream('GET',path+'/snapshots/'+quote(filename,safe='')) as response:
                response.raise_for_status()
                with partial.open('xb') as stream:
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>2*1024**3:raise RuntimeError('Download limit exceeded')
                        digest.update(chunk);stream.write(chunk)
            hashed=digest.hexdigest()
            if size!=snapshot['size']:raise ValueError('Snapshot byte count mismatch')
            if snapshot.get('checksum') and hashed!=snapshot['checksum']:raise ValueError('Qdrant checksum mismatch')
            partial.rename(target)
            receipt={'collection':name,'snapshot':str(target),'bytes':size,'sha256':hashed,
                'provider_checksum_verified':bool(snapshot.get('checksum')),'created_at':time.time(),
                'points_before_snapshot':info.json()['result'].get('points_count'),'restore_tested':False,
                'source_api':'http://127.0.0.1:6333','config':info.json()['result'].get('config')}
            target.with_suffix('.manifest.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
            results.append(receipt)
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--directory',required=True)
    parser.add_argument('--resume-latest',action='store_true',help='Reuse existing saved checksums and latest completed source snapshots; never retry an uncertain creation blindly')
    args=parser.parse_args();print(json.dumps({'snapshots':backup(args.config,args.directory,args.resume_latest),'collections_replaced':False}))
