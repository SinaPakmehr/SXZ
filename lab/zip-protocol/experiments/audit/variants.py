"""Diagnostic variants of the engine: little-endian words and extend-then-choose.

Neither variant is wired into the production packer.  They exist to separate
"the data has no exploitable structure" from "this model bank cannot express
the structure that is there".
"""

from __future__ import annotations

import sinuxz.container as container
import sinuxz.models as models
from sinuxz.bitio import BitReader, BitWriter, bits_to_int
from sinuxz.container import Candidate, Packer, formula_cost_bits
from sinuxz.models import Model, Params


class LittleEndianAffine(Model):
    """x[i] = (a + i*d) mod 2**(8*width), written little or big endian."""

    mid = 8
    name = "affine-word"
    FORMATS = ((2, "little"), (4, "little"), (8, "little"), (2, "big"), (4, "big"), (8, "big"))

    def _words(self, bits, width, order):
        w = 8 * width
        if order == "little":
            return [sum(bits_to_int(bits, 8 * ((i * width) + j), 8) << (8 * j)
                        for j in range(width))
                    for i in range(len(bits) // w)]
        return [bits_to_int(bits, i * w, w) for i in range(len(bits) // w)]

    def fit(self, bits) -> list[Params]:
        out = []
        for mode, (width, order) in enumerate(self.FORMATS):
            words = self._words(bits, width, order)
            if len(words) < 3:
                continue
            mask = (1 << (8 * width)) - 1
            a, b, c = words[0], words[1], words[2]
            d = (b - a) & mask
            if (a + 2 * d) & mask != c:
                continue
            out.append((mode, a, d))
        return out

    def encode(self, w: BitWriter, params: Params) -> None:
        mode, a, d = params
        width = self.FORMATS[mode][0]
        w.write(mode, 3)
        w.write(a, 8 * width)
        w.write(d, 8 * width)

    def decode(self, r: BitReader) -> Params:
        mode = r.read(3)
        if mode >= len(self.FORMATS):
            raise ValueError("unknown word format")
        width = self.FORMATS[mode][0]
        return mode, r.read(8 * width), r.read(8 * width)

    def bit_length(self, params: Params) -> int:
        return 3 + 16 * self.FORMATS[params[0]][0]

    def describe(self, params: Params) -> str:
        mode, a, d = params
        width, order = self.FORMATS[mode]
        return f"{self.name} u{8 * width}{order[0]} a={a} d={d}"

    def gen(self, params: Params, nbits: int):
        mode, a, d = params
        width, order = self.FORMATS[mode]
        mask = (1 << (8 * width)) - 1
        produced = 0
        i = 0
        while produced < nbits:
            value = (a + i * d) & mask
            raw = value.to_bytes(width, order)
            for byte in raw:
                for shift in range(7, -1, -1):
                    if produced >= nbits:
                        return
                    yield (byte >> shift) & 1
                    produced += 1
            i += 1


LE_MODEL = LittleEndianAffine()


def install_le() -> None:
    if LE_MODEL not in container.MODELS:
        container.MODELS = [*container.MODELS, LE_MODEL]
    container.MODEL_BY_ID = {**container.MODEL_BY_ID, LE_MODEL.mid: LE_MODEL}
    models.BY_ID = {**models.BY_ID, LE_MODEL.mid: LE_MODEL}


def uninstall_le() -> None:
    container.MODELS = [m for m in container.MODELS if m is not LE_MODEL]
    container.MODEL_BY_ID.pop(LE_MODEL.mid, None)
    models.BY_ID.pop(LE_MODEL.mid, None)


class ExtendThenChoosePacker(Packer):
    """Extend the best few candidates on the window, then rank by extended cost."""

    BEAM = 3

    def find_formula(self, window: bytes, probe_extend: bytes = b""):
        from sinuxz.transforms import TRANSFORMS

        log: list[dict] | None = [] if self.trace is not None else None
        pool: list[tuple[Candidate, int]] = []
        for transform in TRANSFORMS:
            tb = transform.forward(window)
            bits = container.bytes_to_bits(tb)
            for model in self._models:
                for params in model.fit(bits):
                    cover = model.match(params, bits) // 8
                    if log is not None:
                        log.append({"transform": transform.name, "model": model.name,
                                    "params": params, "cover": cover,
                                    "cost_bits": formula_cost_bits(model, params)})
                    if cover < self.min_formula_bytes:
                        continue
                    pool.append((Candidate(transform.tid, model, params, cover,
                                           formula_cost_bits(model, params)), transform.tid))

        best = None
        if pool:
            pool.sort(key=lambda item: item[0].score)
            extending = []
            for cand, tid in pool[: self.BEAM]:
                if len(probe_extend) > len(window) and cand.cover_bytes == len(window):
                    transform = container.TRANSFORM_BY_ID[tid]
                    ext_bits = container.bytes_to_bits(transform.forward(probe_extend))
                    extended = cand.model.match(cand.params, ext_bits) // 8
                    if extended > cand.cover_bytes:
                        cand.cover_bytes = extended
                extending.append(cand)
            best = min(extending, key=lambda c: (c.score, -c.cover_bytes))

        if self.experimental_models:
            from sinuxz.constants import find_reference

            probe = probe_extend if len(probe_extend) > len(window) else window
            match = find_reference(probe, 0, len(probe), self.min_formula_bytes)
            if match is not None:
                cover, params = match
                cand = Candidate(0, models.REFERENCE, params, cover,
                                 formula_cost_bits(models.REFERENCE, params))
                if best is None or (cand.score, -cover) < (best.score, -best.cover_bytes):
                    best = cand
        self._fits = log
        return best
