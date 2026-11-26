import random
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

import bundle
import dsl
import representation as rep
import search
from accelerate import NATIVE, scan_native, scan_python
from controls import linear, optimized_rice, program4, residual4
from corpus import FILES


class ProgramTests(unittest.TestCase):
    def test_composition(self):
        p = dsl.program([
            dsl.lit(b"abcdefgh"), dsl.seq(dsl.SLICE,0,2,4),
            dsl.seq(dsl.REP,1,3), dsl.seq(dsl.MAP,1,1,dsl.XOR,3),
            dsl.seq(dsl.PERM,1,2,2,1), dsl.seq(dsl.CAT,4,0,2,3,4),
        ])
        self.assertEqual(dsl.evaluate(p),b"abcdefgh"+3*b"cdef"+bytes(i^3 for i in b"cdef")+b"cedf")

    def test_recurrence_general_modulus(self):
        p = dsl.recurrence(2,5,17,(1,2,3),(2,3,4),5)
        self.assertEqual(dsl.evaluate(dsl.program([p])),b"\1\0\2\0\3\0\4\0\x0d\0")

    def test_xor_patch(self):
        p = dsl.program([dsl.lit(b"\x01\x02"),dsl.lit(b"\x03\x07"),dsl.seq(dsl.PATCH,0,1)])
        self.assertEqual(dsl.evaluate(p),b"\x02\x05")

    def test_expression_stack_and_ops(self):
        instructions = [8,0,9,1,dsl.SHL,0,9,2,dsl.ADD,0]
        expr = dsl.seq(dsl.EXPR,1,4,251,1,5,len(instructions)//2,*instructions)
        self.assertEqual(dsl.evaluate(dsl.program([expr])),bytes((5,12,26,54)))

    def test_prime_and_constants(self):
        self.assertEqual(dsl.evaluate(dsl.program([dsl.seq(dsl.PRIME,0,1,2)])), b"\3\0\0\0\5\0\0\0")
        for k, expected in enumerate((b"14159",b"71828",b"61803")):
            self.assertEqual(dsl.evaluate(dsl.program([dsl.seq(dsl.CONST,k,0,5)])),expected)

    def test_invalid_wire_and_budget(self):
        for wire in (b"",b"\x80"*14,dsl.program([dsl.seq(dsl.CAT,1,0)]),
                     dsl.program([dsl.lit(b"a"),dsl.seq(dsl.REP,0,dsl.LIMIT+1)]),
                     dsl.program([dsl.seq(dsl.PRIME,0,100000,6)]),
                     dsl.program([dsl.seq(dsl.REC,4,100,1,1,0,0,0)]),
                     dsl.program([dsl.lit(b"a")])+b"\0",dsl.program([b"\x1f"])):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                dsl.evaluate(wire)
        with self.assertRaisesRegex(ValueError,"archive work"):
            dsl.evaluate(dsl.program([dsl.lit(b"a")]),shared=[16])
        with self.assertRaises(ValueError):
            dsl.evaluate(dsl.program([dsl.lit(b"a")]),expected=2)

    def test_frame_malformed(self):
        d = b"text\n"*100
        s = bundle.recipe([rep.raw(d)])[0]
        b = bundle.frame(s,d,3)
        self.assertEqual(bundle.unpack(b),d)
        for bad in (b[:6],b"ABCD"+b[4:],b[:8]+b"\0"*4+b[12:],b+b"\0",b[:-1]):
            with self.assertRaises((ValueError,zstandard.ZstdError)):
                bundle.unpack(bad)

    def test_grammar_and_symbolic(self):
        d = (b"the brown dog and the brown fox see the brown dog\n"*201)
        p,r = search.grammar(d)
        self.assertGreater(r,0)
        self.assertEqual(dsl.evaluate(p),d)
        data = bytearray()
        x = 12071
        for _ in range(69):
            data += x.to_bytes(4,"little")
            x = dsl.operation(dsl.operation(x,7,dsl.ROL,32),7391,dsl.XOR,32)
        node,_ = search.symbolic(bytes(data),4,"astar")
        self.assertIsNotNone(node)
        self.assertEqual(dsl.evaluate(dsl.program([node])),data)


@unittest.skipUnless(NATIVE,"native tool required")
class NativeTests(unittest.TestCase):
    def test_scan_equivalence_and_nonword_alignment(self):
        rng = random.Random(12)
        for n in (32,128,512,8192,65536):
            x = rng.randbytes(17) + linear(2,n) + rng.randbytes(127)
            hits,count = scan_native(x)
            self.assertEqual((hits,count),scan_python(x))
            self.assertTrue(any(h[:2] == (17,n) for h in hits))
            self.assertEqual(dsl.evaluate(search.bytes_graph(x,hits)),x)

    def test_rice_equivalence(self):
        rng = random.Random(1880)
        for width in (2,8,32,64):
            for length in (0,1,7,19,252):
                data = [rng.randrange(1<<width) for _ in range(length)]
                self.assertEqual(optimized_rice(data,width),residual4._best_rice(data,width))

    def test_state_equivalence(self):
        n = 211
        for code,old,params in ((dsl.XORSHIFT,program4.XorShiftBytes,(23456789,1)),
                                 (dsl.LFSR,program4.LfsrBytes,(19,0x21301,0x73205))):
            p = dsl.program([dsl.seq(code,n,*params)])
            expect = old().predict_bytes(params,n)
            self.assertEqual(dsl.evaluate(p),expect)
            with patch.object(dsl,"NATIVE",None):
                self.assertEqual(dsl.evaluate(p),expect)

    def test_spatial_native_matches_python(self):
        data = random.Random(18).randbytes(19*62)
        params = (19,62,3,4,255,7)
        e = dsl.spatial(data,*params,False)
        self.assertEqual(dsl.spatial(e,*params,True),data)
        with patch.object(dsl,"NATIVE",None):
            self.assertEqual(dsl.spatial(data,*params,False),e)
            self.assertEqual(dsl.spatial(e,*params,True),data)
        p,_ = search.spatial_tree(data,19,62,True)
        self.assertEqual(dsl.evaluate(p),data)


class ContainerTests(unittest.TestCase):
    def test_full_corpus_representations(self):
        for _,fmt,p,_ in FILES:
            with self.subTest(path=p.name):
                b = p.read_bytes()
                f,t,_ = rep.represent(b,fmt)
                for sections in (f,t):
                    s = bundle.recipe(sections)[0]
                    self.assertEqual(bundle.unpack(bundle.frame(s,b,3)),b)

    @unittest.skipUnless(rep.PREF,"Preflate bridge required")
    def test_non_vacuous_preflate(self):
        import zlib
        d = random.Random(155).randbytes(3000)*9
        f = zlib.compress(d)[2:-4]
        p = rep.split_deflate(f)
        self.assertIsNotNone(p)
        self.assertEqual(p[0],d)
        self.assertEqual(rep.rejoin_deflate(*p,len(f)),f)


if __name__ == "__main__":
    unittest.main()
