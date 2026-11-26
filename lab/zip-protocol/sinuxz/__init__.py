"""SINUXZ: formula discovery layer on top of a byte-exact container."""

from .container import Packer, inspect, unpack
from .models import MODELS, berlekamp_massey
from .stream import StreamOptions, inspect_stream, pack_stream, unpack_stream

__all__ = [
    "Packer", "pack", "unpack", "inspect", "MODELS", "berlekamp_massey",
    "StreamOptions", "pack_stream", "unpack_stream", "inspect_stream",
]
__version__ = "0.1.0"


def pack(data: bytes, **kwargs) -> bytes:
    return Packer(**kwargs).pack(data)
