from nmigen import *

from .isa import *
from .alu_core import ALSRU_4LUT

from enum import IntEnum

class Flags(IntEnum):
    Z = 0
    S = 1
    C = 2
    V = 3

class Op(IntEnum):
    AND = 0
    OR = 1
    XOR = 2

    ADD = 4
    SUB = 5
    SHIFTROT = 6

class FlagManager(Elaboratable):
    def __init__(self):
        # update flags (set takes precedence over clear)
        self.i_flag_set = Signal(4)
        self.i_flag_clr = Signal(4)

        # updated flag state
        self.o_flags = Signal(4)

    def elaborate(self, platform):
        m = Module()

        curr_flags = Signal(4)
        new_flags = Signal(4)
        m.d.sync += curr_flags.eq(new_flags)
        m.d.comb += self.o_flags.eq(new_flags)

        for flag in Flags:
            with m.If(self.i_flag_set[flag]):
                m.d.comb += new_flags[flag].eq(1)
            with m.Elif(self.i_flag_clr[flag]):
                m.d.comb += new_flags[flag].eq(0)
            with m.Else():
                m.d.comb += new_flags[flag].eq(curr_flags[flag])

        return m


class ALUFrontendUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(2)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(2)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

        # flag interface
        self.i_flags = Signal(4)
        self.o_flag_set = Signal(4)
        self.o_flag_clr = Signal(4)

        # ALU B input storage
        self.o_B0 = Signal(DATA_WIDTH)
        self.o_B1 = Signal(DATA_WIDTH)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i_we):
            with m.If(self.i_waddr == SplW.ALU_B0_OFFSET):
                m.d.sync += self.o_B0.eq(self.i_wdata)
            with m.Elif(self.i_waddr == SplW.ALU_B1_OFFSET):
                m.d.sync += self.o_B1.eq(self.i_wdata)
            with m.Else(): # ALU_FLAGS
                m.d.comb += [
                    self.o_flag_set.eq(self.i_wdata[:4]),
                    self.o_flag_clr.eq(self.i_wdata[4:8] ^ 0xF),
                ]

        # there is only one thing to read so we don't bother listening to the
        # bus signals.
        m.d.comb += self.o_rdata.eq(self.i_flags)

        return m


class ALU(Elaboratable):
    def __init__(self, frontend):
        # data modification interface
        self.i_mod = Signal()
        self.i_mod_type = Signal(6)
        self.i_mod_data = Signal(DATA_WIDTH)
        self.o_mod_data = Signal(DATA_WIDTH)

        # ALU flag manager unit
        self.flags = FlagManager()
        self.o_flags = Signal(4)

        # the ALU's non-modification registers are contained in a special unit
        self.frontend = frontend

        self.core = ALSRU_4LUT(DATA_WIDTH)

    def elaborate(self, platform):
        m = Module()

        m.submodules.core = core = self.core
        m.submodules.flags = flags = self.flags

        # decode modification type
        store_result = Signal()
        b_source = Signal(2)
        is_rotate = Signal()
        shift_right = Signal()
        alu_op = Signal(3)
        m.d.comb += [
            store_result.eq(self.i_mod_type[5]),
            b_source.eq(self.i_mod_type[3:5]),
            is_rotate.eq(self.i_mod_type[4]),
            shift_right.eq(self.i_mod_type[3]),
            alu_op.eq(self.i_mod_type[:3]),
        ]

        # hook up ALU inputs
        m.d.comb += core.i_a.eq(self.i_mod_data)
        with m.Switch(b_source):
            with m.Case(0):
                m.d.comb += core.i_b.eq(0)
            with m.Case(1):
                m.d.comb += core.i_b.eq(1)
            with m.Case(2):
                m.d.comb += core.i_b.eq(self.frontend.o_B0)
            with m.Case(3):
                m.d.comb += core.i_b.eq(self.frontend.o_B1)

        # decode ALU operations
        with m.Switch(alu_op):
            with m.Case(Op.AND):
                m.d.comb += core.c_op.eq(ALSRU_4LUT.Op.AaB)
            with m.Case(Op.OR):
                m.d.comb += core.c_op.eq(ALSRU_4LUT.Op.AoB)
            with m.Case(Op.XOR):
                m.d.comb += core.c_op.eq(ALSRU_4LUT.Op.AxB)
            with m.Case(Op.ADD):
                m.d.comb += core.c_op.eq(ALSRU_4LUT.Op.ApB)
            with m.Case(Op.SUB):
                m.d.comb += core.c_op.eq(ALSRU_4LUT.Op.AmB)
            with m.Case(Op.SHIFTROT):
                m.d.comb += core.c_op.eq(ALSRU_4LUT.Op.SLR)

        m.d.comb += [
            core.i_c.eq(alu_op == Op.SUB), # carry is inverted for subtract
            core.c_dir.eq(Mux(shift_right, ALSRU_4LUT.Dir.R, ALSRU_4LUT.Dir.L)),
            core.i_h.eq(Mux(is_rotate, core.o_h, 0)),
        ]

        # handle ALU results
        alu_flags = Signal(4)
        m.d.comb += [
            self.o_mod_data.eq(Mux(store_result, core.o_o, self.i_mod_data)),
            alu_flags[Flags.Z].eq(core.o_z),
            alu_flags[Flags.S].eq(core.o_s),
            alu_flags[Flags.C].eq(core.o_c),
            alu_flags[Flags.V].eq(core.o_v),

            flags.i_flag_set.eq(
                Mux(self.i_mod, alu_flags, self.frontend.o_flag_set)),
            flags.i_flag_clr.eq(
                Mux(self.i_mod, 0xF, self.frontend.o_flag_clr)),
            self.frontend.i_flags.eq(flags.o_flags),
            self.o_flags.eq(flags.o_flags),
        ]

        return m
