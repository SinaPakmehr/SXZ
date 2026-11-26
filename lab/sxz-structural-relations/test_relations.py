import random
import unittest

import numpy as np
import zstandard

import inputs
import models as m
import wire
from dsl import seq
from study import synthetic


class Relations(unittest.TestCase):
    def test_frozen_layout_full_files(self):
        for family,_,p,_ in inputs.ENTRY:
            with self.subTest(path=p.name):
                b=p.read_bytes()
                parts,_=inputs.structure(b,family)
                l,r=wire.layout(parts)
                self.assertTrue(any(x.group for x in r))
                self.assertEqual(wire.assemble(l,[x.data for x in r],len(b)),b)

    def test_exact_accounting_and_selected_known_relation(self):
        b,(parts,_)=synthetic()
        lay,records=wire.layout(parts)
        options,audit=m.choose(records)
        self.assertTrue(any(x["selected"] in (m.PXOR,m.PSUB,m.PEDIT) for x in audit))
        results={}
        for mode,op in options.items():
            blob,info=wire.encode(b,lay,op)
            self.assertEqual(wire.unpack(blob),b)
            self.assertEqual(len(blob),sum(info[k] for k in ("header_bytes","layout_stored","descriptor_stored","payload_stored")))
            results[mode]=len(blob)
        self.assertLess(results["math"],results["diff"])

    def test_select_fexp_and_lanes_bit_operations(self):
        bits=np.array([0x80000000,0x7f800001,0,0x3f800000],dtype="<u4").tobytes()
        ex=m.predict(bits,seq(m.FEXP,m.vs(-1),1))
        self.assertEqual(m.predict(ex,seq(m.FEXP,m.vs(1),1)),bits)
        d=np.array([2,3,6,0xffffffff,0,7],dtype="<u4").tobytes()
        self.assertEqual(np.frombuffer(m.predict(d,seq(m.LANES,2,3,12)),"<u4").tolist(),
                         [4,6,18,1,3,19])

    def test_special_bitplane_roundtrip_all_patterns(self):
        b=random.Random(11).randbytes(42*4)
        for w in (1,2,4,5):
            self.assertEqual(m.plane(m.plane(b,w),w,True),b)

    def test_parent_shortlist_is_unique_even_when_samples_overlap(self):
        rng=random.Random(2012)
        records=[inputs.Record(rng.randbytes(256),("image",0,16,16),hw=(16,16)) for _ in range(105)]
        earlier=[(i,m.signature(x)) for i,x in enumerate(records[:-1])]
        proposed=m.top_parents(earlier,records[-1],m.signature(records[-1]),records)
        self.assertLessEqual(len(proposed),5)
        self.assertEqual(len(proposed),len(set(proposed)))
        self.assertTrue(all(x<104 for x in proposed))

    def test_decimal_variable_length_and_delta(self):
        x=b'<tag a="0000099">22 more values and 99 and 3849</tag>'
        y=m.predict(x,seq(m.NUM,m.vs(1)))
        self.assertEqual(y,b'<tag a="0000100">23 more values and 100 and 3850</tag>')
        c=m.copy_delta(x,y,True)
        self.assertIsNotNone(c)
        self.assertEqual(m.apply_copy(x,c,len(y)),y)

    def test_xml_lexical_offsets_and_self_closing(self):
        b=b'<root><w:p xmlns:w="x" a=">"> 1234567890</w:p><w:p xmlns:w="x" a=">1234567890" /></root>'
        r=inputs.xml_records(b)
        self.assertEqual(b,b"".join(x.data for x in r))
        self.assertEqual([x.data for x in r if x.group],
                         [b'<w:p xmlns:w="x" a=">"> 1234567890</w:p>',b'<w:p xmlns:w="x" a=">1234567890" />'])

    def test_grammar_exactness(self):
        b=b'<r id="6543">example <other value="same" /> there</r>\n'*400
        la,records=wire.layout([inputs.raw(b)])
        forced,local,stats=wire.grammar_body(b)
        self.assertEqual(wire.ungrammar(forced),b)
        self.assertEqual(wire.ungrammar(local),b)
        self.assertGreater(stats["rules"],0)
        op=m.choose(records)[0]["plain"]
        self.assertEqual(wire.unpack(wire.encode(b,la,op,grammar=forced)[0]),b)

    def test_reject_forward_trailing_and_copy_oob(self):
        with self.assertRaises(ValueError):
            wire.expand(seq(1,m.REF,1,20,0,1,0),b"")
        with self.assertRaises(ValueError):
            m.apply_copy(b"abc",seq(1,2,2),2)
        b=b"abc"
        l,r=wire.layout([inputs.raw(b)])
        blob,info=wire.encode(b,l,m.choose(r)[0]["plain"])
        for bad in (blob+b"\0", b"0000"+blob[4:], blob[:9]+b"\0\0\0\0"+blob[13:], blob[:-2]):
            with self.assertRaises((ValueError,zstandard.ZstdError)):
                wire.unpack(bad)


if __name__=="__main__":
    unittest.main()
