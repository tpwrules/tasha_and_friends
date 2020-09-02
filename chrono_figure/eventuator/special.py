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
