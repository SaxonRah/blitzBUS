#!/usr/bin/env python3
"""RP2350 OpenOCD Tcl-RPC SWD sampler. Read-only; halt/resume only.
Use OpenOCD -f interface/cmsis-dap.cfg -f target/rp2350.cfg.
"""
import argparse, collections, csv, datetime, pathlib, re, socket, subprocess, time

class OpenOCD:
    def __init__(self, host, port):
        self.sock=socket.create_connection((host,port),timeout=8)
        self.sock.settimeout(8)
        self.pending=bytearray()
    def call(self,command):
        self.sock.sendall(command.encode('utf-8')+b'\x1a')
        while b'\x1a' not in self.pending:
            chunk=self.sock.recv(4096)
            if not chunk: raise ConnectionError('OpenOCD Tcl connection closed')
            self.pending.extend(chunk)
            if len(self.pending)>1048576: raise ValueError('OpenOCD response too large')
        pos=self.pending.index(0x1a)
        output=bytes(self.pending[:pos]).decode('utf-8','replace')
        del self.pending[:pos+1]
        # OpenOCD Tcl errors are generally returned as text, not a structured status.
        if re.search(r'(?im)^\s*(error|invalid command name)\s*:',output):
            raise RuntimeError('%s: %s'%(command,output.strip()[:350]))
        return output
    def close(self): self.sock.close()

def parse_pc(response):
    patterns=[r'(?im)^\s*pc\s*(?:\([^\n)]*\))?\s*:\s*(0x[0-9a-f]+)',
              r'(?i)\bpc\s*:\s*(0x[0-9a-f]+)']
    for pattern in patterns:
        m=re.search(pattern,response)
        if m: return int(m.group(1),16)&~1
    raise ValueError('Unexpected reg pc response: '+repr(response[:260]))

def memory_region(pc):
    if 0x20000000<=pc<0x20082000:return 'SRAM'
    if 0x10000000<=pc<0x11000000:return 'FLASH'
    if 0x11000000<=pc<0x12000000:return 'PSRAM'
    return 'OTHER'

def parse_mdb(response,start):
    result={}
    for line in response.splitlines():
        m=re.match(r'\s*(0x[0-9a-fA-F]+)\s*:\s*(.*)$',line)
        if not m:continue
        address=int(m.group(1),16)
        for match in re.finditer(r'(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}(?![0-9A-Fa-f])',m.group(2)):
            result[address]=int(match.group(),16);address+=1
    # OpenOCD may present one row for all data, or multiple rows.
    return bytes(result.get(start+i,0) for i in range(64)) if len(result)>=64 else b''

def write_results(dest,records,counts,exe):
    columns=['sample','utc','pc','region','dump_start','binary','error']
    with (dest/'samples.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(records)
    with (dest/'ranked_pcs.txt').open('w',encoding='utf8') as f:
        for (region,pc),count in counts.most_common():f.write('%5d 0x%08X %s\n'%(count,pc,region))
    if exe:
        with (dest/'instructions.txt').open('w',encoding='utf8') as f:
            for item in records:
                if not item.get('binary'):continue
                start=int(item['dump_start'],16)
                command=[str(exe),'-D','-b','binary','-m','arm','-M','force-thumb',
                         '--adjust-vma=0x%08X'%start,str(dest/item['binary'])]
                try:
                    p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=8)
                    f.write('\n=== sample %s PC %s ===\n%s'%(item['sample'],item['pc'],p.stdout))
                except Exception as e:f.write('Disassembly error: '+str(e)+'\n')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host',default='127.0.0.1')
    ap.add_argument('--port',type=int,default=6666,help='OpenOCD TCL RPC port, not telnet 4444')
    ap.add_argument('--count',type=int,default=80)
    ap.add_argument('--interval',type=float,default=0.25)
    ap.add_argument('--out',default='swd-capture')
    ap.add_argument('--objdump',default=None)
    args=ap.parse_args()
    if args.count<=0:ap.error('--count must be positive')
    dest=pathlib.Path(args.out).resolve();dest.mkdir(parents=True,exist_ok=True)
    records=[];counts=collections.Counter();error_count=0
    client=None
    try:
        client=OpenOCD(args.host,args.port)
        targets=client.call('targets')
        (dest/'targets.txt').write_text(targets,encoding='utf8')
        select=client.call('targets rp2350.dap.core0')
        print('Connected via Tcl RPC; selected core0.')
        print('Each sample halts/resumes core0; do NOT use samples for FPS timings.')
        for i in range(args.count):
            halted=False;record={'sample':i,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            try:
                client.call('halt');halted=True
                response=client.call('reg pc')
                pc=parse_pc(response)
                record['pc']='0x%08X'%pc;region=memory_region(pc)
                record['region']=region;counts[(region,pc)]+=1
                if region in ('SRAM','FLASH'):
                    start=((pc-24)&~3)
                    response=client.call('mdb 0x%08X 64'%start)
                    data=parse_mdb(response,start)
                    if data:
                        binary=dest/('sample_%04d_0x%08X.bin'%(i,start))
                        binary.write_bytes(data)
                        record['binary']=binary.name;record['dump_start']='0x%08X'%start
                    else:
                        record['error']='Memory dump was not parseable'
                else:record['error']='Non-code region; no bytes requested'
            except Exception as error:
                record['error']=str(error);error_count+=1
                print('Sample %d: %s'%(i,error))
            finally:
                if halted:
                    try:
                        client.call('resume')
                    except Exception as error:
                        record['error']=(record.get('error','')+' RESUME FAILED: '+str(error)).strip()
                        records.append(record)
                        print('CRITICAL: failed to resume. Stop sampling and inspect target.')
                        break
            records.append(record)
            if (i+1)%10==0:
                print('%d/%d top=%s errors=%d'%(i+1,args.count,counts.most_common(3),error_count),flush=True)
            if args.interval:time.sleep(max(0,args.interval))
    except KeyboardInterrupt:
        print('Interrupted; saving partial data.')
    finally:
        if client:
            try:client.call('resume')
            except Exception:pass
            client.close()
        write_results(dest,records,counts,args.objdump)
        print('Saved',len(records),'samples in',dest)
        if counts:
            peak=counts.most_common(1)[0]
            if peak[1]>=max(8,len(records)//2):
                print('WARNING: persistent PC 0x%08X in %d samples; check that the benchmark is running and core0 resumes.'%(peak[0][1],peak[1]))
        if not args.objdump:print('Disassembly skipped. Pass --objdump with your full arm-none-eabi-objdump.exe path.')

if __name__=='__main__':main()
