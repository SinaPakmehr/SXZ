import random
import unittest

import numpy as np

import asm as a
from extra import previous,step,fit_lcg,entropy_pack,entropy_unpack
from experiment import plant,trial


class ASMC(unittest.TestCase):
    def test_generation_random_access_every_variant(self):
        rng=random.Random(97)
        for f in range(14):
            if f==10:t=bytes(range(256))
            elif f==11:t=rng.randbytes(4096)
            elif f==13:t=bytes(range(256))*2
            else:t=b""
            s=a.Source(f,149,0,(2147483647,48271,199) if f==12 else ())
            d=a.generate(s,0,40960,t)
            for i in (0,1,7,25,4013,39713):
                self.assertEqual(a.generate(s,i,175,t),d[i:i+175])

    def test_exact_every_bit_mode_unaligned_source(self):
        for mode in a.MODES:
            nb,ns=a.rp.UNITS[mode]
            s=a.Source(0,37)
            data=a.generate(s,nb*2,nb*12)
            raw=b"xyz"*3+data+b"xyz"
            pos=9
            e=a.Edge(pos,pos+len(data),s,2*ns,12*ns)
            b,cost=a.arch(raw,a.sequences(raw,[e]),mode,True)
            self.assertEqual(a.decode(b),raw)
            self.assertEqual(len(b),sum(cost[k] for k in ("header_bytes","meta_bytes","literals_bytes")))

    def test_bank_match_verifies_addresses_no_fence_crossing(self):
        s=a.Source(0,11)
        d=b"??"+a.generate(s,3,42)+b"????"
        with a.Bank([(0,0,a.seeds(8))]) as ix:
            h,st=ix.search(d)
        self.assertIn(a.Edge(2,44,s,3,42),h)
        for g in h:self.assertEqual(a.generate(g.source,g.address,g.symbols),d[g.start:g.end])

    def test_group_one_seed_shared_multiple_segments(self):
        d,loc=plant("shared")
        with a.Bank([(0,0,np.arange(1024,dtype=np.uint32))],1536) as ix:
            h,st=ix.search(d)
        m=trial(d,h,more=True)
        self.assertEqual(m["methods"]["B"]["sources"],1)
        self.assertGreaterEqual(m["methods"]["B"]["exact_runs"],10)
        self.assertEqual(m["methods"]["B-affine"]["groups_affine"],1)
        self.assertLess(m["methods"]["B-affine"]["bytes"],m["methods"]["A"]["bytes"])

    def test_singleton_inadmissible_for_B(self):
        v=a.Edge(0,80,a.Source(0,11),0,80)
        w=a.Edge(1,80,a.Source(0,11),1,79)
        self.assertEqual(a.group_candidates([v,w]),[])

    def test_same_segmentation_zstd_identical(self):
        d=b"prefix--"+a.generate(a.Source(0,4),0,30)+b"--suffix"
        e=a.Edge(8,38,a.Source(0,4),0,30)
        g,_=a.arch(d,a.sequences(d,[e]))
        ctrl,_=a.arch(d,a.sequences(d,[e],True))
        self.assertEqual(a.decode(g),a.decode(ctrl))
        n=a.HEADER.unpack_from(g)[-1]
        self.assertEqual(g[-n:],ctrl[-n:])

    def test_general_lcg_and_inverse(self):
        for x in (0,1,4568187,0xf8d1d301,0xffffffff):
            self.assertEqual(previous(step(x)),x)
        s=a.Source(12,511030,0,(2147483629,6291,312))
        d=a.generate(s,0,512)
        self.assertEqual(fit_lcg(d[:128]),s)
        e=a.Edge(0,len(d),s,0,len(d))
        for o in (False,True):self.assertEqual(a.decode(a.arch(d,a.sequences(d,[e]),group=o)[0]),d)

    def test_probability_codes_exact(self):
        raw=b"aABCCCD---"*600
        for width in (16,256):
            lut=a.lookup(a.train_counts(raw,width==16),width)
            b,p=entropy_pack(raw,lut,width)
            self.assertEqual(entropy_unpack(b),raw)

    def test_patching_modes(self):
        s=a.Source(0,78);base=a.generate(s,3,24);data=base[:4]+b"xx"+base[6:]
        es=((a.XOR,bytes(x^y for x,y in zip(base,data))), (a.MODDIFF,bytes((y-x)&255 for x,y in zip(base,data))),
            (a.PATCH,a.ints(2,4,120,1,120)))
        for op,p in es:
            e=a.Edge(0,len(data),s,3,24,p,op)
            self.assertEqual(a.decode(a.arch(data,a.sequences(data,[e]))[0]),data)

    def test_reject_bad_frame_length_or_checksum(self):
        d=b"sample"
        p=a.arch(d,a.sequences(d,[]))[0]
        for bad in (p[:-1],b"\0"+p[1:],p[:10]+b"\0\0\0\0"+p[14:],p+b"\xff"):
            with self.assertRaises(ValueError):a.decode(bad)


if __name__=="__main__":unittest.main()
