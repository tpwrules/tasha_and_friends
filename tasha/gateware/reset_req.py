# let boneless reset the system

from nmigen import *

# 0x0: (W) Reset enable
#   Write:   15-0: reset enable key
#   Write 0xFADE to enable the "Perform reset" register. The register will
#   disable itself after 7 clock cycles.

# 0x1: (W) Perform reset
#   Write:   15-0: perform reset key
#   Write 0xDEAD to reset the system. How long exactly it takes the system to
#   reset is undefined, but it will certainly be within the next few dozen clock
#   cycles or so.

# RECOMMENDED OPERATION SEQUENCE
#   MOVI(R0, 0xFADE),
#   MOVI(R1, 0xDEAD),
#   STXA(R0, base+0),
#   STXA(R1, base+1),
#   J(-1),

class ResetReq(Elaboratable):
    def __init__(self):
        # boneless bus inputs
        self.i_re = Signal()
        self.i_we = Signal()
        self.i_addr = Signal(4)
        self.o_rdata = Signal(16)
        self.i_wdata = Signal(16)

        # reset output. never goes low (until, of course, reset)
        self.o_reset_req = Signal() # active high

    def elaborate(self, platform):
        m = Module()

        # nothing to read
        m.d.comb += self.o_rdata.eq(0)

        # latch bus to avoid impacting timing basically at all
        did_write = Signal()
        which_reg = Signal()
        written_data = Signal(16)
        m.d.sync += [
            did_write.eq(self.i_we),
            which_reg.eq(self.i_addr[0]),
            written_data.eq(self.i_wdata),
        ]

        unlock_counter = Signal(3)
        unlocked = Signal()
        m.d.comb += unlocked.eq(unlock_counter != 0)
        with m.If(unlocked):
            m.d.sync += unlock_counter.eq(unlock_counter - 1)

        with m.If(did_write):
            with m.If((which_reg == 0) & (written_data == 0xFADE)):
                m.d.sync += unlock_counter.eq(7)
            with m.Elif((which_reg == 1) & (written_data == 0xDEAD) & unlocked):
                m.d.sync += self.o_reset_req.eq(1)

        return m
