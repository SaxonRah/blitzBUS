#!/usr/bin/env python3
"""Capture longer RP2350 JIT code windows over OpenOCD Tcl RPC; no firmware modifications."""
import argparse,csv,collections,datetime,pathlib,re,socket,subprocess,time

class OCD:
    def __init__(self,host,port):
        self.s=socket.create_connection((host,port),8);self.s.settimeout(8);self.buf=bytearray()
    def cmd(self,q):
        self.s.sendall(q.encode()+b'\x1a')
        while b'\x1a' not in self.buf:
            data=self.s.recv(8192)
            if not data:raise ConnectionError('OpenOCD closed connection')
            self.buf.extend(data)
            if len(self.buf)>2000000:raise ValueError('OpenOCD response overflow')
        n=self.buf.index(26);response=self.buf[:n].decode('utf8','replace');del self.buf[:n+1]
        if re.search(r'(?im)^\s*(?:error|invalid command name)\s*:',response):raise RuntimeError(q+': '+response[:200])
        return response
    def close(self):self.s.close()

def get_pc(s):
    m=re.search(r'(?im)^\s*pc\s*(?:\([^\r\n]*\))?\s*:\s*(0x[0-9a-f]+)',s)
    if not m:raise ValueError('Bad PC response: '+repr(s[:150]))
    return int(m.group(1),16)&~1

def bytes_from_mdb(s,start,length):
    found={}
    for line in s.splitlines():
        m=re.match(r'\s*(0x[0-9A-Fa-f]+)\s*:\s*(.*)',line)
        if not m:continue
        a=int(m.group(1),16)
        for v in re.findall(r'(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}(?![0-9A-Fa-f])',m.group(2)):
            found[a]=int(v,16);a+=1
    missing=[a for a in range(start,start+length) if a not in found]
    if missing:raise ValueError('Incomplete memory read at 0x%08X'%missing[0])
    return bytes(found[a] for a in range(start,start+length))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=6666)
    p.add_argument('--attempts',type=int,default=160);p.add_argument('--max-blocks',type=int,default=24)
    p.add_argument('--interval',type=float,default=0.10)
    p.add_argument('--jit-start',type=lambda s:int(s,0),default=0x2002A040)
    p.add_argument('--jit-size',type=lambda s:int(s,0),default=0x3A000)
    p.add_argument('--before',type=int,default=128);p.add_argument('--after',type=int,default=384)
    p.add_argument('--out',default='logs/swd_jit_v3');p.add_argument('--objdump',required=True)
    a=p.parse_args()
    if a.attempts<1 or a.max_blocks<1 or a.interval<0 or a.before<0 or a.after<16: p.error('invalid capture parameters')
    if not pathlib.Path(a.objdump).is_file():p.error('objdump executable does not exist: '+a.objdump)
    dest=pathlib.Path(a.out).resolve()
    if dest.exists() and any(dest.iterdir()):p.error('output folder already contains files; choose a new --out')
    dest.mkdir(parents=True,exist_ok=True)
    counts=collections.Counter();rows=[];client=None;stopped=False
    end=a.jit_start+a.jit_size
    try:
        client=OCD(a.host,a.port)
        (dest/'targets.txt').write_text(client.cmd('targets'),encoding='utf8')
        client.cmd('targets rp2350.dap.core0')
        print('Connected. Sampling core0. Samples HALT the target; do not use FPS from this run.',flush=True)
        for i in range(a.attempts):
            halted=False;row={'attempt':i,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pc':'','kind':'','start':'','length':'','binary':'','error':''}
            try:
                client.cmd('halt');halted=True
                pc=get_pc(client.cmd('reg pc'));row['pc']='0x%08X'%pc
                in_jit=a.jit_start<=pc<end
                row['kind']='JIT' if in_jit else ('SRAM' if 0x20000000<=pc<0x20082000 else 'FLASH' if 0x10000000<=pc<0x11000000 else 'OTHER')
                counts[row['kind']]+=1
                if in_jit and sum(bool(r['binary']) for r in rows)<a.max_blocks:
                    # Align to 4, never read beyond reserved cache. PC appears 128 bytes into dump.
                    start=max(a.jit_start,(pc-a.before)&~3)
                    stop=min(end,(pc+a.after+3)&~3)
                    size=stop-start
                    parts=[]
                    for pos in range(start,stop,64):
                        n=min(64,stop-pos)
                        parts.append(bytes_from_mdb(client.cmd('mdb 0x%08X %u'%(pos,n)),pos,n))
                    data=b''.join(parts)
                    filename='jit_%04d_pc_%08X_at_%08X.bin'%(i,pc,start)
                    (dest/filename).write_bytes(data)
                    row.update(start='0x%08X'%start,length=size,binary=filename)
            except Exception as exc:
                row['error']=str(exc);print('attempt',i,'ERROR:',exc,flush=True)
            finally:
                if halted:
                    try:client.cmd('resume')
                    except Exception as exc:
                        row['error']+=' RESUME FAILED '+str(exc);stopped=True
            rows.append(row)
            if (i+1)%20==0 or stopped:
                print('%d/%d JIT=%d captured=%d other=%s'%(i+1,a.attempts,counts['JIT'],sum(bool(r['binary']) for r in rows),dict(counts)),flush=True)
            if stopped or sum(bool(r['binary']) for r in rows)>=a.max_blocks:break
            if a.interval:time.sleep(a.interval)
    except KeyboardInterrupt:print('Interrupted: saving everything collected.',flush=True)
    finally:
        if client:
            try:client.cmd('resume')
            except Exception:pass
            client.close()
        with (dest/'samples.csv').open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,['attempt','utc','pc','kind','start','length','binary','error']);w.writeheader();w.writerows(rows)
        with (dest/'jit_disassembly.txt').open('w',encoding='utf8') as f:
            for r in rows:
                if not r['binary']:continue
                call=[a.objdump,'-D','-b','binary','-m','arm','-M','force-thumb','--adjust-vma='+r['start'],str(dest/r['binary'])]
                result=subprocess.run(call,capture_output=True,text=True,timeout=15)
                f.write('\n=== attempt %s PC %s dump %s (%s bytes) ===\n'%(r['attempt'],r['pc'],r['start'],r['length']))
                f.write(result.stdout+result.stderr+'\n')
        with (dest/'summary.txt').open('w',encoding='utf8') as f:
            f.write('Attempts: %d\nRegion counts: %s\nJIT code cache: 0x%08X..0x%08X\n'%(len(rows),dict(counts),a.jit_start,end-1))
            f.write('Captured windows: %d\n'%sum(bool(r['binary']) for r in rows))
            f.write('Note: byte dumps begin at 4-byte boundaries, NOT assured Thumb instruction boundaries.\n')
            f.write('The PC may be in the middle of generated code; inspect from reliable entry points to disambiguate Thumb32 widths.\n')
            f.write('Guest CS:IP cannot be recovered from PC alone without JIT metadata; correlate with v49f reports.\n')
        print('SAVED:',dest,flush=True)
        print('Upload samples.csv + jit_disassembly.txt + binary dumps zipped together.',flush=True)
if __name__=='__main__':main()
