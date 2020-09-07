from nmigen import *

from chrono_figure.gateware.match_engine import make_match_info
from chrono_figure.gateware.match_info import *
from .isa import *
from .core import EventuatorCore
from .alu import ALU, ALUFrontendUnit
from .special import *
from .special_map import special_map

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
        self.o_match_config = Signal(8)
        self.o_match_config_addr = Signal(10)
        self.o_match_config_we = Signal()

        # event data fifo signals
        self.o_event = Signal(31)
        self.o_event_we = Signal()
        self.i_event_space = Signal() # space for more valid events

        self.spl_alu_frontend = ALUFrontendUnit()
        self.spl_temp = TemporaryUnit()
        self.spl_imm = ImmediateUnit()
        self.spl_event_fifo = EventFIFOUnit()
        self.spl_match_config = MatcherConfigUnit()

        self.core = EventuatorCore()
        self.alu = ALU(self.spl_alu_frontend)

    def elaborate(self, platform):
        m = Module()

        m.submodules.core = core = self.core
        m.submodules.alu = alu = self.alu

        # automatically wire up passed through signals
        for name in set(dir(self)) & set(dir(core)):
            if name.startswith("i_"):
                m.d.comb += getattr(core, name).eq(getattr(self, name))
            elif name.startswith("o_"):
                m.d.comb += getattr(self, name).eq(getattr(core, name))

        # wire up all the special units using the generated map
        all_rdata = Const(0, DATA_WIDTH)
        spl_re = self.core.o_spl_re
        spl_we = self.core.o_spl_we
        spl_raddr = self.core.o_spl_raddr
        spl_waddr = self.core.o_spl_waddr
        for unit_name, unit_map in special_map.items():
            # attach the unit's module
            unit = getattr(self, unit_name)
            m.submodules[unit_name] = unit
            # hook up the special bus to it
            mask = (2**SPL_WIDTH-1) ^ (2**unit_map["width"]-1)
            m.d.comb += [
                unit.i_raddr.eq(spl_raddr),
                unit.i_re.eq(spl_re & ((spl_raddr & mask) == unit_map["base"])),
                unit.i_waddr.eq(spl_waddr),
                unit.i_we.eq(spl_we & ((spl_waddr & mask) == unit_map["base"])),
                unit.i_wdata.eq(self.core.o_spl_wdata),
            ]
            # mux the data read from the unit back to the core
            unit_was_re = Signal(name=unit_name+"_was_re")
            m.d.sync += unit_was_re.eq(unit.i_re)
            all_rdata = all_rdata | Mux(unit_was_re, unit.o_rdata, 0)

        m.d.comb += self.core.i_spl_rdata.eq(all_rdata)

        # hook up the other special unit connections
        m.d.comb += [
            # ALU
            alu.i_mod_type.eq(core.o_mod_type[:6]),
            alu.i_mod_data.eq(core.o_mod_data),
            core.i_flags.eq(alu.o_flags),
            # event FIFO
            self.o_event.eq(self.spl_event_fifo.o_event),
            self.o_event_we.eq(self.spl_event_fifo.o_event_we),
            # matcher config
            self.o_match_config.eq(self.spl_match_config.o_match_config),
            self.o_match_config_addr.eq(
                self.spl_match_config.o_match_config_addr),
            self.o_match_config_we.eq(self.spl_match_config.o_match_config_we),
        ]

        # test modify functionality
        with m.If(core.o_mod_type == Mod.COPY):
            m.d.comb += core.i_mod_data.eq(core.o_mod_data)
        with m.Elif(core.o_mod_type & 0xC0 == 0xC0):
            m.d.comb += [
                core.i_mod_data.eq(alu.o_mod_data),
                alu.i_mod.eq(core.o_mod),
            ]

        return m
