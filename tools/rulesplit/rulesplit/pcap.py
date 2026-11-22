"""Bounded classic-PCAP Ethernet/IPv4 TCP/UDP reader, never a packet sender."""
import struct
def encode_pcap(packets):
    out=bytearray(struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,1))
    for n,(src,dst,sport,dport,proto) in enumerate(packets):
        if proto not in (6,17):raise ValueError('Fixture generator supports TCP and UDP')
        transport=struct.pack('!HH',sport,dport)+(b'\0'*16 if proto==6 else struct.pack('!HH',8,0))
        header=struct.pack('!BBHHHBBHII',0x45,0,20+len(transport),n%65536,0,64,proto,0,src,dst)
        words=struct.unpack('!10H',header);checksum=sum(words);checksum=(checksum&65535)+(checksum>>16);checksum=(checksum&65535)+(checksum>>16)
        header=header[:10]+struct.pack('!H',(~checksum)&65535)+header[12:]
        ethernet=b'\x02\0\0\0\0\x01\x02\0\0\0\0\x02\x08\0'
        packet=ethernet+header+transport
        out.extend(struct.pack('<IIII',1700000000+n//1000,(n%1000)*1000,len(packet),len(packet))+packet)
    return bytes(out)

def read_pcap(blob):
    if len(blob)<24:raise ValueError('Truncated PCAP header')
    magic=blob[:4]
    endian='<' if magic in (b'\xd4\xc3\xb2\xa1',b'\x4d\x3c\xb2\xa1') else '>' if magic in (b'\xa1\xb2\xc3\xd4',b'\xa1\xb2\x3c\x4d') else None
    if endian is None:raise ValueError('Only classic PCAP is supported, not PCAP-NG')
    _,major,minor,_,_,snaplen,link=struct.unpack(endian+'IHHIIII',blob[:24])
    if (major,minor)!=(2,4) or link!=1:raise ValueError('Only Ethernet PCAP 2.4 is supported')
    if snaplen>65535:raise ValueError('PCAP snaplen exceeds 65535')
    offset=24;packets=[]
    while offset<len(blob):
        if len(blob)-offset<16:raise ValueError('Truncated PCAP record')
        _,_,length,original=struct.unpack_from(endian+'IIII',blob,offset);offset+=16
        if length>snaplen or length>original or offset+length>len(blob):raise ValueError('Truncated or invalid captured frame')
        frame=blob[offset:offset+length];offset+=length
        if len(frame)<14:raise ValueError('Truncated Ethernet frame')
        etype=int.from_bytes(frame[12:14],'big');pos=14
        if etype==0x8100:
            if len(frame)<18:raise ValueError('Truncated VLAN frame')
            etype=int.from_bytes(frame[16:18],'big');pos=18
        if etype!=0x0800:raise ValueError('Non-IPv4 frame: keep unsupported traffic on CPU outside this tool')
        ip=frame[pos:]
        if len(ip)<20 or ip[0]>>4!=4 or (ip[0]&15)<5:raise ValueError('Invalid IPv4 header')
        ihl=(ip[0]&15)*4;total=int.from_bytes(ip[2:4],'big');fragment=int.from_bytes(ip[6:8],'big')
        if fragment&0x3fff:raise ValueError('Fragmented IPv4 is not supported')
        if total>len(ip) or total<ihl+4 or ihl>len(ip):raise ValueError('Truncated IPv4 datagram')
        proto=ip[9]
        if proto not in (6,17):raise ValueError('Only TCP/UDP captures are supported')
        if total<ihl+(20 if proto==6 else 8):raise ValueError('Truncated transport header')
        src=int.from_bytes(ip[12:16],'big');dst=int.from_bytes(ip[16:20],'big');sport,dport=struct.unpack('!HH',ip[ihl:ihl+4])
        packets.append((src,dst,sport,dport,proto))
        if len(packets)>1_000_000:raise ValueError('Capture exceeds one million packets')
    return packets
