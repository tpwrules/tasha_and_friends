# stolen (and subsequently modified) from Boneless

from enum import Enum, EnumMeta
from nmigen import *

__all__ = ["ALSRU", "ALSRU_4LUT"]

# We have to do an annoying metaclass dance because we want to do something like:
#
#   class MuxA(Enum): ...
#   class MuxB(Enum): ...
#   class Mode(EnumGroup):
#       FOO = (MuxA.X, MuxB.Y)
#
# but by the time we're inside the body of `Mode` it is no longer possible to access the names from
# the outer scope, so we can't easily name `MuxA` for example, so we rewrite it as:
#
#   class Mode(EnumGroup, layout=[MuxA, MuxB]):
#       FOO = ("X", "Y")
class EnumGroupMeta(EnumMeta):
    @classmethod
    def __prepare__(metacls, name, bases, **kwargs):
        return super().__prepare__(name, bases)

    def __new__(cls, name, bases, classdict, layout=None):
        if layout is not None:
            classdict, old_classdict = type(classdict)(), classdict

            offsets = []
            offset  = 0
            for enum in layout.values():
                offsets.append(offset)
                offset += Shape.cast(enum).width

            for key in old_classdict:
                if key.startswith("_"):
                    classdict[key] = old_classdict[key]
                else:
                    value = 0
                    for item, enum, offset in zip(old_classdict[key], layout.values(), offsets):
                        value |= enum[item].value << offset
                    classdict[key] = value

            @classmethod
            def expand(cls, m, signal):
                rec = Record([*layout.items()], src_loc_at=1)
                m.d.comb += rec.eq(signal)
                return rec
            classdict["expand"] = expand

        return super().__new__(cls, name, bases, classdict)


class EnumGroup(Enum, metaclass=EnumGroupMeta):
    def foo(self):
        pass


class ALSRU:
    """Arithmetical, logical, shift, and rotate unit."""

    # redefined by subclasses
    class Op(EnumGroup):
        A    = ()
        B    = ()
        nB   = ()
        AaB  = ()
        AoB  = ()
        AxB  = ()
        ApB  = ()
        AmB  = ()
        SLR  = ()

    class Dir(Enum):
        L    = ()
        R    = ()

    def __init__(self, width):
        self.width = width

        self.i_a = Signal(width)
        self.i_b = Signal(width)
        self.i_c = Signal()
        self.o_o = Signal(width)

        self.o_z = Signal() # zero out
        self.o_s = Signal() # sign out
        self.o_c = Signal() # carry out
        self.o_v = Signal() # overflow out

        self.c_op  = Signal(self.Op) # redefined by subclasses

        self.i_h = Signal() # shift in
        self.o_h = Signal() # shift out

        self.c_dir = Signal(self.Dir)


class ALSRU_4LUT(ALSRU, Elaboratable):
    """ALSRU optimized for 4-LUT architecture with no adder pre-inversion.

    On iCE40 with Yosys, ABC, and -relut this synthesizes to the optimal 4n+3 LUTs.
    """

    # The block diagram of an unit cell is as follows:
    #
    #              A-|‾\       CO
    #                |3 |-X-·  |   O       SLn+1
    #              B-|_/    |_|‾\  |  ___    |
    #                       ._|4 |-·-|D Q|-R-·
    #              B-|‾\    | |_/    |>  |   |
    #   SRn+1-|‾\    |2 |-Y-·  |      ‾‾‾  SRn-1
    #         |1 |-S-|_/       CI
    #   SLn-1-|_/
    #
    # LUT 1 computes: R<<1, R>>1
    # LUT 2 computes: B, ~B, 0, S
    # LUT 3 computes: A&B, A|B, A^B, A
    # LUT 4 computes: X+Y, Y
    #
    # To compute:
    #      A:          X=A    Y=0   O=X+Y
    #      B:                 Y=B   O=Y
    #     ~B:                 Y=~B  O=Y
    #    A&B:          X=A&B  Y=0   O=X+Y
    #    A|B:          X=A|B  Y=0   O=X+Y
    #    A^B:          X=A^B  Y=0   O=X+Y
    #    A+B:          X=A    Y=B   O=X+Y
    #    A-B:          X=A    Y=~B  O=X+Y  (pre-invert CI)
    #   A<<1: S=SLn-1         Y=S   O=Y
    #   A>>1: S=SRn+1         Y=S   O=Y

    class XMux(Enum):
        A   = 0b00
        AaB = 0b01
        AoB = 0b10
        AxB = 0b11
        x   = 0

    class YMux(Enum):
        Z   = 0b00
        S   = 0b01
        B   = 0b10
        nB  = 0b11

    class OMux(Enum):
        XpY = 0b0
        Y   = 0b1

    class Op(EnumGroup, layout={"x":XMux, "y":YMux, "o":OMux}):
        A    = ("A",   "Z",  "XpY",)
        B    = ("x",   "B",  "Y",  )
        nB   = ("x",   "nB", "Y",  )
        AaB  = ("AaB", "Z",  "XpY",)
        AoB  = ("AoB", "Z",  "XpY",)
        AxB  = ("AxB", "Z",  "XpY",)
        ApB  = ("A",   "B",  "XpY",)
        AmB  = ("A",   "nB", "XpY",)
        SLR  = ("x",   "S",  "Y",  )

    class Dir(Enum):
        L    = 0b0
        R    = 0b1

    def elaborate(self, platform):
        m = Module()

        dec_op = self.Op.expand(m, self.c_op)

        s_s = Signal(self.width)
        with m.Switch(self.c_dir):
            with m.Case(self.Dir.L):
                m.d.comb += s_s.eq(Cat(self.i_h, self.i_a[:-1]))
                m.d.comb += self.o_h.eq(self.i_a[-1])
            with m.Case(self.Dir.R):
                m.d.comb += s_s.eq(Cat(self.i_a[ 1:], self.i_h))
                m.d.comb += self.o_h.eq(self.i_a[ 0])

        s_x = Signal(self.width)
        with m.Switch(dec_op.x):
            with m.Case(self.XMux.AaB):
                m.d.sync += s_x.eq(self.i_a & self.i_b)
            with m.Case(self.XMux.AoB):
                m.d.sync += s_x.eq(self.i_a | self.i_b)
            with m.Case(self.XMux.AxB):
                m.d.sync += s_x.eq(self.i_a ^ self.i_b)
            with m.Case(self.XMux.A):
                m.d.sync += s_x.eq(self.i_a)

        s_y = Signal(self.width)
        with m.Switch(dec_op.y):
            with m.Case(self.YMux.Z):
                m.d.sync += s_y.eq(0)
            with m.Case(self.YMux.S):
                m.d.sync += s_y.eq(s_s)
            with m.Case(self.YMux.B):
                m.d.sync += s_y.eq(self.i_b)
            with m.Case(self.YMux.nB):
                m.d.sync += s_y.eq(~self.i_b)

        s_p = Signal(self.width)
        m.d.comb += Cat(s_p, self.o_c).eq(s_x + s_y + self.i_c)

        op_o = Signal(len(dec_op.o))
        m.d.sync += op_o.eq(dec_op.o)
        with m.Switch(op_o):
            with m.Case(self.OMux.XpY):
                m.d.comb += self.o_o.eq(s_p)
            with m.Case(self.OMux.Y):
                m.d.comb += self.o_o.eq(s_y)

        # http://teaching.idallen.com/cst8214/08w/notes/overflow.txt
        with m.Switch(Cat(s_x[-1], s_y[-1], self.o_o[-1])):
            with m.Case(0b100):
                m.d.comb += self.o_v.eq(1)
            with m.Case(0b011):
                m.d.comb += self.o_v.eq(1)

        m.d.comb += self.o_z.eq(self.o_o == 0)
        m.d.comb += self.o_s.eq(self.o_o[-1])

        return m

# -------------------------------------------------------------------------------------------------

import argparse
from nmigen import cli


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--type",  choices=["4lut"], default="4lut")
    parser.add_argument("-w", "--width", type=int, default=16)
    cli.main_parser(parser)

    args = parser.parse_args()
    if args.type == "4lut":
        alsru = ALSRU_4LUT(args.width)
        ctrl  = (alsru.op, alsru.dir)

    ports = (
        alsru.a,  alsru.b,  alsru.o,  alsru.r,
        alsru.ci, alsru.co, alsru.vo,
        alsru.si, alsru.so,
        *ctrl
    )
    cli.main_runner(parser, args, alsru, name="alsru", ports=ports)
