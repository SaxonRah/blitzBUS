#!/usr/bin/env python3
"""Read-only RP2350 SWD sampler via an already running OpenOCD telnet server.
Never issues reset, flash, program or memory writes.
"""
import argparse, collections, csv, datetime, pathlib, re, socket, subprocess, sys, time

PROMPT = b'> '

def recv_prompt(sock):
    data = bytearray()
    while len(data) < 262144:
        chunk = sock.recv(65536)
        if not chunk: raise RuntimeError('OpenOCD closed the telnet connection')
        data += chunk
        if data.rstrip().endswith(b'>'): break
    return data.decode('utf-8', 'replace')

def cmd(sock, command):
    sock.sendall((command+'\n').encode('ascii'))
    return recv_prompt(sock)

def parse_pc(output):
    # Typical OpenOCD: pc (/32): 0x20003108 ; or pc ... 0x....
    m=re.search(r'(?im)^\s*pc\s*(?:\([^\n)]*\))?\s*:\s*(0x[0-9a-fA-F]+)', output)
    if not m: m=re.search(r'(?i)\bpc\b[^\n]*?\b(0x[0-9a-fA-F]{6,8})\b',output)
    return int(m.group(1),16) if m else None

def region(pc):
    if 0x20000000<=pc<0x20082000: return 'SRAM'
    if 0x10000000<=pc<0x11000000: return 'FLASH'
    if 0x11000000<=pc<0x12000000: return 'PSRAM'
    return 'OTHER'

def dump_bytes(output):
    # OpenOCD mdb output: 0x20000000: 5a 4c ... ; some versions one byte per line
    chunks=[]
    for line in output.splitlines():
        m=re.match(r'\s*0x[0-9a-fA-F]+:\s*((?:[0-9a-fA-F]{2}(?:\s+|$))+)',line)
        if m: chunks.extend(int(s,16) for s in m.group(1).split())
    return bytes(chunks)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=4444)
    p.add_argument('--count',type=int,default=80)
    p.add_argument('--interval',type=float,default=0.25,help='Seconds between intrusive halt/resume samples')
    p.add_argument('--out',default='swd-capture')
    p.add_argument('--objdump',default='arm-none-eabi-objdump')
    p.add_argument('--elf',help='Existing exact firmware ELF for address-to-symbol lookup, optional')
    a=p.parse_args()
    dest=pathlib.Path(a.out).resolve();dest.mkdir(parents=True,exist_ok=True)
    raw=[];count=collections.Counter()
    with socket.create_connection((a.host,a.port),timeout=10) as s:
        s.settimeout(15); banner=recv_prompt(s)
        (dest/'openocd_banner.txt').write_text(banner,encoding='utf8')
        print('Connected. Each sample briefly halts CPU; benchmark FPS will be disturbed.')
        for i in range(a.count):
            halted=False
            try:
                halt=cmd(s,'halt'); halted=True
                reg=cmd(s,'reg pc')
                pc=parse_pc(reg)
                if pc is None: raise RuntimeError('Cannot parse PC register: '+repr(reg[:300]))
                r=region(pc); count[(r,pc)]+=1
                # Read a small instruction window for this exact PC while the target is halted.
                # CPU core executing SRAM JIT code may rewrite it after resume; capturing now matters.
                start=max(0,(pc&~1)-24)
                start&=~3
                hexdump=cmd(s,'mdb 0x%08x 64'%start) if r in ('SRAM','FLASH') else ''
                data=dump_bytes(hexdump)
                record={'sample':i,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'pc':'0x%08X'%pc,'region':r,'dump_start':'0x%08X'%start,
                    'bytes_hex':data.hex(),'pc_raw':reg.strip()}
                raw.append(record)
                if data:
                    # binary snapshots allow Thumb-2 disassembly of runtime-generated code
                    fn=dest/('sample_%04d_0x%08X.bin'%(i,start));fn.write_bytes(data)
                    record['binary']=fn.name
                else: record['binary']=''
            except Exception as exc:
                print('Sample %d failed: %s'%(i,exc),file=sys.stderr)
                raw.append({'sample':i,'error':str(exc)})
            finally:
                if halted:
                    try: cmd(s,'resume')
                    except Exception as exc: print('WARNING: RESUME FAILED: %s'%exc,file=sys.stderr);break
            if (i+1)%10==0:print('%d/%d samples; top %s'%(i+1,a.count,count.most_common(3)))
            time.sleep(max(0.0,a.interval))
    fields=['sample','timestamp_utc','pc','region','dump_start','bytes_hex','pc_raw','binary','error']
    with (dest/'samples.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(raw)
    with (dest/'ranked_pcs.txt').open('w',encoding='utf8') as f:
        for (r,pc),n in count.most_common():f.write('%5d 0x%08X %s\n'%(n,pc,r))
    # Offline disassembly: snapshots, including unmodified JIT byte sequences
    with (dest/'instructions.txt').open('w',encoding='utf8') as f:
        for record in raw:
            if not record.get('binary'):continue
            pc=int(record['pc'],16); start=int(record['dump_start'],16)
            args=[a.objdump,'-D','-b','binary','-m','arm','-M','force-thumb',
                  '--adjust-vma=0x%08X'%start,str(dest/record['binary'])]
            f.write('\n===== sample %s PC %s %s =====\n'%(record['sample'],record['pc'],record['region']))
            try:
                z=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
                f.write(z.stdout if z.returncode==0 else 'objdump failed: '+z.stdout)
            except Exception as e: f.write('objdump unavailable: '+str(e)+'\n')
    print('Wrote',dest/'samples.csv',dest/'ranked_pcs.txt',dest/'instructions.txt')
    if a.elf:print('ELF reference:',a.elf,'(use arm-none-eabi-addr2line -Cfipe <ELF> <PC> for flash/SRAM linked functions)')

if __name__=='__main__':main()
