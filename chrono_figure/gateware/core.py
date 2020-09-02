from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.back import verilog

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .snes_bus import SNESBus
from .match_engine import MatchEngine, make_match_info
from .eventuator.eventuator import Eventuator
from .eventuator import isa

# will probably always be manually incremented because it's related to the
# modules in the sd2snes and its firmware as well
GATEWARE_VERSION = 1000

class ChronoFigureCore(Elaboratable):
    def __init__(self, cart_signals):
        self.i_config = Signal(32) # configuration word
        self.i_config_addr = Signal(8) # which matcher to apply it to
        self.i_config_we = Signal() # write word to the address

        # connection to the event FIFO
        self.o_event = Signal(31)
        self.o_event_valid = Signal()
        self.i_event_re = Signal() # acknowledge the data

        # version constant output for the get version command
        self.o_gateware_version = Const(GATEWARE_VERSION, 32)

        self.event_fifo = SyncFIFOBuffered(width=31, depth=128)
        self.bus = SNESBus(cart_signals)
        self.match_engine = MatchEngine()
        
        self.eventuator = Eventuator()
        self.ev_prg_mem = Memory(width=isa.INSN_WIDTH, depth=1024, init=[0])
        self.ev_reg_mem = Memory(width=isa.DATA_WIDTH, depth=256)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = self.bus
        m.submodules.event_fifo = event_fifo = self.event_fifo
        m.submodules.match_engine = match_engine = self.match_engine

        m.submodules.eventuator = eventuator = self.eventuator
        m.submodules.ev_prg_rd = ev_prg_rd = self.ev_prg_mem.read_port(
            transparent=False)
        m.submodules.ev_prg_wr = ev_prg_wr = self.ev_prg_mem.write_port()
        m.submodules.ev_reg_rd = ev_reg_rd = self.ev_reg_mem.read_port(
            transparent=False)
        m.submodules.ev_reg_wr = ev_reg_wr = self.ev_reg_mem.write_port()

        # hook up match engine to the bus
        m.d.comb += [
            # temporary, will be attached to eventuator soon
            match_engine.i_config.eq(self.i_config),
            match_engine.i_config_addr.eq(self.i_config_addr),
            match_engine.i_config_we.eq(self.i_config_we),

            match_engine.i_bus_valid.eq(bus.o_valid),
            match_engine.i_bus_addr.eq(bus.o_addr),
            match_engine.i_bus_data.eq(bus.o_data),
            match_engine.i_cycle_count.eq(bus.o_cycle_count),
        ]

        # hook up the eventuator's inputs and outputs
        m.d.comb += [
            Cat(*eventuator.i_match_info).eq(Cat(*match_engine.o_match_info)),
            eventuator.i_match_valid.eq(match_engine.o_match_valid),
            match_engine.i_match_re.eq(eventuator.o_match_re),

            event_fifo.w_data.eq(eventuator.o_event),
            event_fifo.w_en.eq(eventuator.o_event_valid),
            eventuator.i_event_space.eq(event_fifo.w_rdy),
        ]

        # hook the eventuator's memories to it
        m.d.comb += [
            ev_prg_rd.addr.eq(eventuator.o_prg_addr),
            ev_prg_rd.en.eq(1),
            eventuator.i_prg_data.eq(ev_prg_rd.data),

            ev_reg_rd.addr.eq(eventuator.o_reg_raddr),
            ev_reg_rd.en.eq(eventuator.o_reg_re),
            eventuator.i_reg_rdata.eq(ev_reg_rd.data),

            ev_reg_wr.addr.eq(eventuator.o_reg_waddr),
            ev_reg_wr.en.eq(eventuator.o_reg_we),
            ev_reg_wr.data.eq(eventuator.o_reg_wdata),
        ]

        # hook up event fifo to the output
        m.d.comb += [
            self.o_event.eq(event_fifo.r_data),
            self.o_event_valid.eq(event_fifo.r_rdy),
            event_fifo.r_en.eq(self.i_event_re),
        ]

        return m
