from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered

from chrono_figure.gateware.match_engine import make_match_info
from ..eventuator import Eventuator
from ..core import EventuatorCore
from .. import isa

# simulate just the eventuation core
class SimCoreTop(Elaboratable):
    def __init__(self, prg_d=1024, reg_d=256):
        self.core = EventuatorCore()
        self.prg_mem = Memory(width=isa.INSN_WIDTH, depth=prg_d, init=[0])
        self.reg_mem = Memory(width=isa.DATA_WIDTH, depth=reg_d)

        self.o_clk = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.core = core = self.core
        m.submodules.ev_prg_rd = ev_prg_rd = self.prg_mem.read_port(
            transparent=False)
        m.submodules.ev_prg_wr = ev_prg_wr = self.prg_mem.write_port()
        m.submodules.ev_reg_rd = ev_reg_rd = self.reg_mem.read_port(
            transparent=False)
        m.submodules.ev_reg_wr = ev_reg_wr = self.reg_mem.write_port()

        # hook the eventuator's memories to it
        m.d.comb += [
            ev_prg_rd.addr.eq(core.o_prg_addr),
            ev_prg_rd.en.eq(1),
            core.i_prg_data.eq(ev_prg_rd.data),

            ev_reg_rd.addr.eq(core.o_reg_raddr),
            ev_reg_rd.en.eq(core.o_reg_re),
            core.i_reg_rdata.eq(ev_reg_rd.data),

            ev_reg_wr.addr.eq(core.o_reg_waddr),
            ev_reg_wr.en.eq(core.o_reg_we),
            ev_reg_wr.data.eq(core.o_reg_wdata),
        ]

        m.d.comb += self.o_clk.eq(ClockSignal())

        return m

# simulate the whole eventuation system
class SimTop(Elaboratable):
    def __init__(self, match_d=256, event_d=512, prg_d=1024, reg_d=256):
        # smaller depths simulate faster
        self.match_fifo = SyncFIFOBuffered(width=72, depth=match_d)
        self.event_fifo = SyncFIFOBuffered(width=32, depth=event_d)

        self.ev = Eventuator()
        self.prg_mem = Memory(width=isa.INSN_WIDTH, depth=prg_d, init=[0])
        self.reg_mem = Memory(width=isa.DATA_WIDTH, depth=reg_d)

        # write match into fifo
        self.i_match_info = make_match_info()
        self.i_match_we = Signal()
        self.o_match_space = Signal()

        # read event from fifo
        self.o_event = Signal(32)
        self.o_event_valid = Signal()
        self.i_event_re = Signal()

        self.o_clk = Signal()

    def elaborate(self, platform):
        m = Module()

        enable_match_fifo = Signal()
        m.submodules.match_fifo = match_fifo = \
            ResetInserter(~enable_match_fifo)(self.match_fifo)
        m.submodules.event_fifo = event_fifo = self.event_fifo

        m.submodules.ev = ev = self.ev
        m.submodules.ev_prg_rd = ev_prg_rd = self.prg_mem.read_port(
            transparent=False)
        m.submodules.ev_prg_wr = ev_prg_wr = self.prg_mem.write_port()
        m.submodules.ev_reg_rd = ev_reg_rd = self.reg_mem.read_port(
            transparent=False)
        m.submodules.ev_reg_wr = ev_reg_wr = self.reg_mem.write_port()

        # hook the eventuator's memories to it
        m.d.comb += [
            ev_prg_rd.addr.eq(ev.o_prg_addr),
            ev_prg_rd.en.eq(1),
            ev.i_prg_data.eq(ev_prg_rd.data),

            ev_reg_rd.addr.eq(ev.o_reg_raddr),
            ev_reg_rd.en.eq(ev.o_reg_re),
            ev.i_reg_rdata.eq(ev_reg_rd.data),

            ev_reg_wr.addr.eq(ev.o_reg_waddr),
            ev_reg_wr.en.eq(ev.o_reg_we),
            ev_reg_wr.data.eq(ev.o_reg_wdata),
        ]

        # hook the FIFOs up too
        m.d.comb += [
            match_fifo.w_data.eq(Cat(*self.i_match_info)),
            match_fifo.w_en.eq(self.i_match_we),
            self.o_match_space.eq(match_fifo.w_rdy),

            Cat(*ev.i_match_info).eq(match_fifo.r_data),
            ev.i_match_valid.eq(match_fifo.r_rdy),
            match_fifo.r_en.eq(ev.o_match_re),

            event_fifo.w_data.eq(ev.o_event),
            event_fifo.w_en.eq(ev.o_event_we),
            ev.i_event_space.eq(event_fifo.w_rdy),
            ev.i_event_empty.eq(~event_fifo.r_rdy),

            self.o_event.eq(event_fifo.r_data),
            self.o_event_valid.eq(event_fifo.r_rdy),
            event_fifo.r_en.eq(self.i_event_re),
        ]
        with m.If(ev.i_ctl_stop):
            m.d.sync += enable_match_fifo.eq(0)
        with m.Elif(ev.o_match_enable):
            m.d.sync += enable_match_fifo.eq(1)

        m.d.comb += self.o_clk.eq(ClockSignal())

        return m
