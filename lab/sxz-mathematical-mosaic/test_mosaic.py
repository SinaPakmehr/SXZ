import random
import unittest
from collections import Counter
from pathlib import Path

import catalog as c
import index
import measure as e
import mosaic as m
import represent as r


class Mosaic(unittest.TestCase):
    def test_radices_and_aligned_subspan(self):
        raw=b"\0"*19+random.Random(73).randbytes(248)
        for mode in r.MODES:
            with self.subTest(mode=mode):
                s,p=r.view(raw,mode)
                a,b,sh,n,w=r.project(mode,p,0,len(s))
                self.assertEqual(r.revert(s[sh:sh+n],mode,w),raw[a:b])
                a,b,sh,n,w=r.project(mode,p,3,len(s)-9)
                self.assertEqual(r.revert(s[3+sh:3+sh+n],mode,w),raw[a:b])

    def test_all_sources_prefix_and_alphabet(self):
        for mode in r.MODES:
            a,p=c.generate(mode,8192)
            for i,v in enumerate(a):
                self.assertEqual(c.stream(i,mode,len(v)+20)[:len(v)],v)
                self.assertTrue(all(x<r.BASE[mode] for x in v))

    def test_bbp_and_arb(self):
        for p in (0,7,208,1408):
            a=c.bbp(p,24)
            self.assertEqual(a,c.constant("pi",(),p+24,16)[p:])
        self.assertEqual(c.bbp(0,12),bytes((2,4,3,15,6,10,8,8,8,5,10,3)))

    def test_shuffled_exact_histogram(self):
        for mo in ("bytes","decvar"):
            mats,_=c.generate(mo,8192)
            control,_=c.generate(mo,8192,"shuffled",2,mats)
            for a,b in zip(mats,control):
                self.assertEqual(Counter(a),Counter(b))

    def test_random_access_byte_sources(self):
        lengths=c.sizes(100000)
        for i,n in enumerate(lengths):
            ref=c.stream(i,"bytes",n)
            for p in (0,1,18,n-45):
                x=c.direct(i,"bytes",p,31,n)
                if x is not None:
                    self.assertEqual(ref[p:p+31],x)

    def test_index_all_byte_positions_and_source_boundaries(self):
        a=[b"__abcdefghijklmnopq",b"rstuvwxyz",b"23456789"]
        d=b"?defghijklmnopqrs?789?"
        with index.Index(a,"bytes") as ix:
            h,stats=ix.query(d,min_len=3)
        self.assertIn((1,0,5,14),h)
        self.assertNotIn((1,0,5,16),h)
        self.assertIn((18,2,5,3),h)
        for p,g,o,n in h: self.assertEqual(a[g][o:o+n],d[p:p+n])

    def test_graph_beats_longest_first(self):
        edges=[m.Edge(0,40,1,0,40),m.Edge(0,54,1,0,54),m.Edge(40,100,1,0,60)]
        a=m.plan(edges,"dp"); b=m.plan(edges,"greedy")
        self.assertEqual([(x.a,x.b) for x in a],[(0,40),(40,100)])
        self.assertEqual([(x.a,x.b) for x in b],[(0,54)])

    def test_roundtrip_on_all_archive_styles(self):
        a,_=c.generate("bytes",1000000)
        d,p=e.synthetic()
        with index.Index(a,"bytes") as ix:
            h,_=ix.query(d)
        edges=m.expanded_edges(h,"bytes",None)
        for arch in (False,True):
            s=m.definitions(d,m.plan(edges),arch)
            for style in (0,1,3):
                for delta in (False,True):
                    b,t=m.archive(d,s,"bytes","math",0,1000000,style,delta)
                    self.assertEqual(m.decode(b),d)
                    self.assertEqual(len(b),sum(t[k] for k in ("header_bytes","metadata_bytes","literals_bytes")))

    def test_nonbyte_archive_consumes_widths(self):
        rng=random.Random(185)
        d=b"\0"*9+rng.randbytes(191)
        for mode in r.MODES[1:]:
            s,off=r.view(d,mode)
            lo,hi,t,n,w=r.project(mode,off,1,len(s)-2)
            block=s[1+t:1+t+n]
            op=m.Edge(lo,hi,0,17,n,w)
            b,_=m.archive(d,m.definitions(d,[op]),mode,"math",0,8192,3)
            class Bank:
                def get(self,k,mo,to,seed,gid,pos,n): return block
            self.assertEqual(m.decode(b,Bank()),d)

    def test_invalid_crc_extent_orig_and_ref(self):
        d=b"hello world!"
        b,_=m.archive(d,e.base_ops(d),"bytes","math",0,8192,3)
        for bad in (b[:-1],b+b"\0",b"MSM1"+b[4:],b[:13]+b"\0\0\0\0"+b[17:]):
            with self.assertRaises(ValueError):
                m.decode(bad)
        b,_=m.archive(d,[(m.COPY,0,len(d),len(d))],"bytes","math",0,8192,0)
        with self.assertRaises(ValueError): m.decode(b)

    def test_literal_in_metadata_control(self):
        d=b"abcd"+b"\0"*24+b"xy"
        ops=[(m.LIT,0,4,None),(m.INLINE,4,28,None),(m.LIT,28,len(d),None)]
        b,t=m.archive(d,ops,"bytes","math",0,8192,3)
        self.assertEqual(m.decode(b),d)
        self.assertEqual(t["literals_raw"],6)
        self.assertEqual(t["covered_bytes"],0)


if __name__=="__main__":
    unittest.main()
