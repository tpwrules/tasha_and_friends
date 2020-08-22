from nmigen import *

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *

class Matcher(Elaboratable):
    def __init__(self):
        self.i_snes_addr = Signal(24) # address the snes is accessing
        self.i_snes_rd = Signal() # 1 the cycle the snes starts reading

        # configuration input to set type and address
        self.i_config_data = Signal(8)
        self.i_config_we = Signal(4) # one per byte

        self.o_match_type = Signal(MATCH_TYPE_BITS)

    def elaborate(self, platform):
        m = Module()

        match_addr = Signal(24)
        match_type = Signal(MATCH_TYPE_BITS)

        with m.If(self.i_config_we[0]):
            m.d.sync += match_addr[0:8].eq(self.i_config_data)
        with m.If(self.i_config_we[1]):
            m.d.sync += match_addr[8:16].eq(self.i_config_data)
        with m.If(self.i_config_we[2]):
            m.d.sync += match_addr[16:24].eq(self.i_config_data)
        with m.If(self.i_config_we[3]):
            m.d.sync += match_type.eq(self.i_config_data[0:MATCH_TYPE_BITS])

        with m.If(self.i_snes_rd):
            with m.If(self.i_snes_addr == match_addr):
                m.d.comb += self.o_match_type.eq(match_type)

        return m
