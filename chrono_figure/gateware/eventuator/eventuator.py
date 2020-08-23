from nmigen import *

from ..match_info import *
from .widths import *
from ..match_engine import make_match_info
from .core import EventuatorCore
from .instructions import *

class Eventuator(Elaboratable):
    def __init__(self):
        # execution control signals
        self.i_ctl_start = Signal() # start execution at the below address
        self.i_ctl_pc = Signal(PC_WIDTH)
        self.o_ctl_run = Signal() # currently running
        self.i_ctl_stop = Signal() # stop execution now
        # jumping to address 0 deasserts run that cycle. if start is asserted,
        # the jump goes to the given PC instead and run is asserted next cycle.
        # asserting stop forces a jump to address 0 that cycle.
        
        # program memory access signals
        # (read is always enabled, even when stopped)
        self.o_prg_addr = Signal(PC_WIDTH)
        self.i_prg_data = Signal(INSN_WIDTH)

        # register memory access signals (dual port)
        self.o_reg_raddr = Signal(REGS_WIDTH)
        self.o_reg_re = Signal()
        self.i_reg_rdata = Signal(DATA_WIDTH)
        self.o_reg_waddr = Signal(REGS_WIDTH)
        self.o_reg_we = Signal()
        self.o_reg_wdata = Signal(DATA_WIDTH)

        # match info input signals
        self.i_match_info = make_match_info()
        self.i_match_valid = Signal()
        self.o_match_re = Signal()

        # match config access signals
        self.o_match_config = Signal(32)
        self.o_match_config_addr = Signal(8)
        self.o_match_config_we = Signal()

        # event data fifo signals
        self.o_event = Signal(31)
        self.o_event_we = Signal()
        self.i_event_space = Signal() # space for more valid events

        self.core = EventuatorCore()

    def elaborate(self, platform):
        m = Module()

        m.submodules.core = core = self.core

        # automatically wire up passed through signals
        for name in set(dir(self)) & set(dir(core)):
            if name.startswith("i_"):
                m.d.comb += getattr(core, name).eq(getattr(self, name))
            elif name.startswith("o_"):
                m.d.comb += getattr(self, name).eq(getattr(core, name))

        # store to load forwarding logic. if the eventuator reads the same
        # regular register it's writing to it should read what it's writing
        forward = Signal()
        forward_data = Signal(DATA_WIDTH)
        m.d.sync += [
            forward.eq((core.o_reg_raddr == core.o_reg_waddr) &
                (core.o_reg_re == 1) & (core.o_reg_we == 1)),
            forward_data.eq(core.o_reg_wdata),
        ]
        with m.If(forward):
            m.d.comb += core.i_reg_rdata.eq(forward_data)

        # test special register functionality
        spl_reg = Signal(DATA_WIDTH)
        is_spl_addr = Signal()
        m.d.comb += [
            is_spl_addr.eq(core.o_spl_addr == Special.TEST),
            core.i_spl_data.eq(spl_reg),
        ]
        with m.If(core.o_spl_we & is_spl_addr):
            m.d.sync += spl_reg.eq(core.o_spl_data)

        # test modify functionality
        with m.If(core.o_mod_type == Mod.COPY):
            m.d.comb += core.i_mod_data.eq(core.o_mod_data)

        return m
