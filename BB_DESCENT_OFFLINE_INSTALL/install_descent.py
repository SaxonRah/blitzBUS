#!/usr/bin/env python3
"""Offline installer for user's own Descent five-disk FAT12 images into blitzBUS FAT16 C:.
Requires BB_DESCENT_IMPORT and BB_FAT16_TOOL siblings and a compatible ARJ extractor.
No image modified until archive extraction and FAT16 image verification succeed.
"""
import argparse, importlib.util, os, pathlib, shutil, subprocess, sys, tempfile, hashlib
P=pathlib.Path
class InstallError(Exception): pass

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise InstallError(f'Missing dependency: {path}')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def locate_extractor(explicit):
    choices=[explicit] if explicit else ['7z.exe','7za.exe','7z','7za','arj.exe','arj']
    choices += [r'C:\Program Files\7-Zip\7z.exe',r'C:\Program Files (x86)\7-Zip\7z.exe']
    for name in choices:
        if not name: continue
        found=shutil.which(name)
        if found:return P(found)
        if P(name).is_file():return P(name)
    raise InstallError('ARJ extractor not found. Install 7-Zip or ARJ and supply --extractor PATH.')

def safe_tree(root):
    entries=[]
    for f in sorted(root.rglob('*')):
        if f.is_symlink():raise InstallError('Symlinks not supported: '+str(f))
        rel=f.relative_to(root)
        if any(part in ('.','..') for part in rel.parts):raise InstallError('Unsafe archive path: '+str(rel))
        entries.append((rel,f))
    return entries

def run_extractor(exe,archive,outdir):
    cmd=([str(exe),'x','-y','-aoa',f'-o{outdir}',str(archive)] if '7z' in exe.name.lower()
         else [str(exe),'x','-y',str(archive),str(outdir)+os.sep])
    p=subprocess.run(cmd,capture_output=True,text=True,errors='replace',cwd=str(archive.parent))
    log=' '.join(cmd)+'\n'+p.stdout+'\n'+p.stderr
    return p.returncode,log[-12000:]

def collect_images(games,reader):
    blobs=[]
    for n in range(1,6):
        floppy=reader.DOSFloppy(games/f'descent_disk{n}.img')
        names={path.upper():data for path,data in floppy.files() if data is not None}
        key=f'DESCENT{n}.SOW'
        if key not in names:raise InstallError(f'Disk {n}: {key} not found')
        blobs.append(names[key]);print(f'DISK {n}: {key} {len(names[key]):,} bytes')
    return blobs

def extract(blobs,stage,extractor):
    stage.mkdir(parents=True,exist_ok=True)
    if any(stage.iterdir()):raise InstallError(f'Staging directory must be empty: {stage}')
    # ARJ multi-volume split sets often use a sequential raw byte stream.
    # Try both raw joined stream and native ARJ volume names; NEVER accept partial failure.
    diagnostics=[]
    with tempfile.TemporaryDirectory(prefix='bb-descent-arj-') as temp:
        t=P(temp)
        merged=t/'descent.arj';merged.write_bytes(b''.join(blobs))
        variants=[('joined',merged)]
        volumes=t/'volumes';volumes.mkdir()
        (volumes/'descent.arj').write_bytes(blobs[0])
        for i,data in enumerate(blobs[1:]):(volumes/f'descent.a{i:02d}').write_bytes(data)
        variants.append(('volumes',volumes/'descent.arj'))
        for label,archive in variants:
            target=t/f'extracted_{label}';target.mkdir()
            rc,log=run_extractor(extractor,archive,target)
            files=[x for x in target.rglob('*') if x.is_file()]
            diagnostics.append((label,rc,len(files),log))
            if rc==0 and files:
                for p in target.iterdir():shutil.move(str(p),str(stage/p.name))
                print(f'ARJ extraction successful ({label}): {len(files)} files')
                return
    for label,rc,count,log in diagnostics:
        print(f'---- {label} extractor rc={rc}, files={count} ----\n{log[-1500:]}',file=sys.stderr)
    raise InstallError('Could not extract complete ARJ archive. No C: image changed. Send the extractor messages.')

def destination_files(stage,fatmod):
    entries=safe_tree(stage)
    if not entries:raise InstallError('No extracted files')
    seen=set();outputs=[]
    for rel,src in entries:
        parts=[x.upper() for x in rel.parts]
        for item in parts:fatmod.dosname(item)
        key='/'.join(parts)
        if key in seen:raise InstallError('Case-insensitive duplicate: '+key)
        seen.add(key);outputs.append((key,src))
    return outputs

def write_image(stage,image,root,fatmod,dry_run):
    entries=destination_files(stage,fatmod)
    files=[(name,f) for name,f in entries if f.is_file()]
    total=sum(f.stat().st_size for _,f in files)
    print(f'Installed output candidate: {len(files)} files, {total:,} bytes, {sum(f.is_dir() for _,f in entries)} directories')
    if not files:raise InstallError('No installation files found')
    if not any(name.endswith(('.EXE','.HOG','.PIG')) for name,_ in files):raise InstallError('Archive output lacks recognizable Descent files')
    fat=fatmod.FAT16(bytearray(image.read_bytes()))
    free=sum(fat.fat(c)==0 for c in range(2,fat.clusters+2))*fat.spc*512
    allocated=sum(((f.stat().st_size+fat.spc*512-1)//(fat.spc*512))*(fat.spc*512) for _,f in files)
    print(f'C: free {free:,} bytes; installed data requires at least {allocated:,} bytes in clusters')
    if allocated + 2*1024*1024 > free:raise InstallError('Insufficient C: space with 2 MiB safety margin')
    try:fat.resolve(root)
    except fatmod.FatError as e:
        if not str(e).startswith('Not found:'):raise
    else:raise InstallError(f'{root} already exists in image; refusing overwrite')
    if dry_run:
        for name,src in files:print('  '+name+f' ({src.stat().st_size:,} bytes)')
        print('DRY RUN: C: not modified');return
    parent=''
    for part in root.replace('\\','/').strip('/').split('/'):
        parent=f'{parent}/{part}'.strip('/')
        try:fat.resolve(parent)
        except fatmod.FatError as e:
            if not str(e).startswith('Not found:'):raise
            fat.mkdir(parent)
    for rel,src in entries:
        dest=root+'/'+rel
        if src.is_dir():fat.mkdir(dest)
        else:
            fat.importfile(src,dest)
            _,ent=fat.resolve(dest)
            if hashlib.sha256(fat.filebytes(ent)).digest()!=hashlib.sha256(src.read_bytes()).digest():
                raise InstallError(f'FAT16 verification failed: {dest}')
    fatmod.save_atomic(image,fat.d)
    print(f'SUCCESS: installed into {root} in {image}')
    print('Original floppy images unchanged. Back up the updated C: image before first Pico boot.')

def main():
    pa=argparse.ArgumentParser(description='Offline Descent installer for blitzBUS FAT16 C: image')
    pa.add_argument('--games',default=r'C:\blitzBUS\games')
    pa.add_argument('--image',default=r'O:\BLITZBUS\DRIVE_C.IMG')
    pa.add_argument('--stage',default=r'C:\blitzBUS\descent_extracted')
    pa.add_argument('--root',default='GAMES/DESCENT')
    pa.add_argument('--extractor',help='Path to 7z.exe or arj.exe')
    pa.add_argument('--extract-only',action='store_true')
    pa.add_argument('--install-only',action='store_true')
    pa.add_argument('--dry-run',action='store_true')
    a=pa.parse_args()
    if a.extract_only and a.install_only:pa.error('Choose either --extract-only or --install-only')
    here=P(__file__).resolve().parent
    reader=load(here.parent/'BB_DESCENT_IMPORT'/'import_descent.py','bb_descent_reader')
    fatmod=load(here.parent/'BB_FAT16_TOOL'/'fat16tool.py','bb_fat16_manager')
    stage=P(a.stage)
    if not a.install_only:
        blobs=collect_images(P(a.games),reader)
        extractor=locate_extractor(a.extractor)
        print('Extractor:',extractor)
        extract(blobs,stage,extractor)
    if a.extract_only:
        print('Extraction complete; C: unchanged');return
    image=P(a.image)
    if not image.is_file():raise InstallError('FAT16 image not found: '+str(image))
    if not a.dry_run:
        print('CAUTION: Pico must be OFF. Back up the C: image first.')
    write_image(stage,image,a.root.strip('/').replace('\\','/').upper(),fatmod,a.dry_run)

if __name__=='__main__':
    try:main()
    except (InstallError,OSError,ValueError,Exception) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
