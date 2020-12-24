from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.back import verilog

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .snes_bus import SNESBus, make_cart_signals
from .match_engine import MatchEngine, make_match_info
from chrono_figure.eventuator.eventuator import Eventuator
from chrono_figure.eventuator import isa

# will probably always be manually incremented because it's related to the
# modules in the sd2snes and its firmware as well
GATEWARE_VERSION = 1002

class ChronoFigureCore(Elaboratable):
    def __init__(self, cart_signals):
        self.i_prg_insn = Signal(isa.INSN_WIDTH) # program instruction
        self.i_prg_addr = Signal(isa.PC_WIDTH) # what address to write to
        self.i_prg_we = Signal() # write instruction to the address

        # connection to the event FIFO
        self.o_event = Signal(32)
        self.o_event_valid = Signal()
        self.i_event_re = Signal() # acknowledge the data

        # version constant output for the get version command
        self.o_gateware_version = Const(GATEWARE_VERSION, 32)

        self.event_fifo = SyncFIFOBuffered(width=32, depth=512)
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
            match_engine.i_config.eq(eventuator.o_match_config),
            match_engine.i_config_addr.eq(eventuator.o_match_config_addr),
            match_engine.i_config_we.eq(eventuator.o_match_config_we),

            match_engine.i_bus_valid.eq(bus.o_valid),
            match_engine.i_bus_addr.eq(bus.o_addr),
            match_engine.i_bus_data.eq(bus.o_data),
            match_engine.i_cycle_count.eq(bus.o_cycle_count),
            Cat(*match_engine.i_cart_signals).eq(Cat(*bus.o_cart_signals)),
        ]

        # hook up the eventuator's inputs and outputs
        m.d.comb += [
            Cat(*eventuator.i_match_info).eq(Cat(*match_engine.o_match_info)),
            eventuator.i_match_valid.eq(match_engine.o_match_valid),
            match_engine.i_match_re.eq(eventuator.o_match_re),
            match_engine.i_match_bus_trace.eq(eventuator.o_match_bus_trace),

            event_fifo.w_data.eq(eventuator.o_event),
            event_fifo.w_en.eq(eventuator.o_event_we),
            eventuator.i_event_space.eq(event_fifo.w_rdy),
            eventuator.i_event_empty.eq(~event_fifo.r_rdy),
        ]

        wiggle = Signal()
        m.d.sync += wiggle.eq(~wiggle)

        # hook the eventuator's memories to it
        m.d.comb += [
            ev_prg_rd.addr.eq(eventuator.o_prg_addr),
            ev_prg_rd.en.eq(1),
            eventuator.i_prg_data.eq(ev_prg_rd.data),

            # quartus refuses to infer a BRAM for the registers on account of
            # "asynchronous read logic" so we put something clock-related
            # on the address that doesn't change the overall behavior to fool it
            ev_reg_rd.addr.eq(eventuator.o_reg_raddr | wiggle),
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
        with m.If(eventuator.i_ctl_stop):
            m.d.sync += match_engine.i_reset_match_fifo.eq(1)
        with m.Elif(eventuator.o_match_enable):
            m.d.sync += match_engine.i_reset_match_fifo.eq(0)

        # handle writes to program memory
        m.d.sync += [
            ev_prg_wr.addr.eq(self.i_prg_addr),
            ev_prg_wr.data.eq(self.i_prg_insn),
            ev_prg_wr.en.eq(self.i_prg_we & (self.i_prg_addr != 0)),
        ]

        stop_timer = Signal(3) # make ultra turbo mega sure everything stops
        with m.If(stop_timer > 0):
            m.d.sync += stop_timer.eq(stop_timer-1)
            m.d.comb += eventuator.i_ctl_stop.eq(1)

        # writing to address 0 controls execution: zero stops execution and
        # non-zero starts execution (if stopped) at the written address
        m.d.sync += [
            eventuator.i_ctl_pc.eq(self.i_prg_insn[:isa.PC_WIDTH]),
            eventuator.i_ctl_start.eq(0),
        ]
        with m.If(self.i_prg_we & (self.i_prg_addr == 0)):
            with m.If(self.i_prg_insn[:isa.PC_WIDTH] == 0):
                m.d.sync += stop_timer.eq(7) # write 0 = stopping
            with m.Else():
                m.d.sync += eventuator.i_ctl_start.eq(1)

        return m
