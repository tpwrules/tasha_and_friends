from nmigen import *

from .isa import *

# stores two temporary values TMPA and TMPB
# does store to load forwarding
class TemporaryUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(1)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(1)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

    def elaborate(self, platform):
        m = Module()

        # forwarding logic so a read of the same register on the same cycle as a
        # write will read the new value instead of the old one
        rdata = Signal(DATA_WIDTH)
        forward = Signal()
        forward_data = Signal(DATA_WIDTH)
        m.d.sync += [
            forward.eq((self.i_raddr == self.i_waddr) &
                (self.i_re == 1) & (self.i_we == 1)),
            forward_data.eq(self.i_wdata),
        ]
        m.d.comb += self.o_rdata.eq(Mux(forward, forward_data, rdata))

        tmp_a = Signal(DATA_WIDTH)
        tmp_b = Signal(DATA_WIDTH)

        with m.If(self.i_we):
            with m.If(self.i_waddr == SplW.TMPA_OFFSET):
                m.d.sync += tmp_a.eq(self.i_wdata)
            with m.Elif(self.i_waddr == SplW.TMPB_OFFSET):
                m.d.sync += tmp_b.eq(self.i_wdata)
        with m.If(self.i_re):
            with m.If(self.i_raddr == SplR.TMPA_OFFSET):
                m.d.sync += rdata.eq(tmp_a)
            with m.Elif(self.i_raddr == SplR.TMPB_OFFSET):
                m.d.sync += rdata.eq(tmp_b)

        return m


# assists in generating full 32 bit immediates. writing to the Bn register
# stores the low 8 bits of the value to byte n and sign extends the 9th bit to
# all bytes above n. it does not touch bytes below n.
class ImmediateUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(2)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(2)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

    def elaborate(self, platform):
        m = Module()

        immediate = Signal(DATA_WIDTH)

        ext_data = Cat(self.i_wdata[:8], Repl(self.i_wdata[8], 24))
        with m.If(self.i_we):
            with m.Switch(self.i_waddr):
                for byte in range(4):
                    with m.Case(getattr(SplW, "IMM_B{}_OFFSET".format(byte))):
                        m.d.sync += immediate.eq(
                            Cat(immediate[:byte*8], ext_data))

        # there is only one thing to read so we don't bother listening to the
        # bus signals. assigning it combinatorially means store to load
        # forwarding is not necessary
        m.d.comb += self.o_rdata.eq(immediate)

        return m
