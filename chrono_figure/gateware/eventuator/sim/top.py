from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.sim.pysim import Simulator, Delay

from ..eventuator import Eventuator
from .. import widths
from ...match_info import *
from ...match_engine import make_match_info
from ..widths import *
from ..instructions import *

class SimTop(Elaboratable):
    def __init__(self, match_depth=256, event_depth=128):
        self.match_fifo = SyncFIFOBuffered(width=72, depth=match_depth)
        self.event_fifo = SyncFIFOBuffered(width=31, depth=event_depth)

        self.ev = Eventuator()
        self.prg_mem = Memory(
            width=widths.INSN_WIDTH, depth=1024, init=[int(BRANCH(0))])
        self.reg_mem = Memory(
            width=widths.DATA_WIDTH, depth=256)

        # write match into fifo
        self.i_match_info = make_match_info()
        self.i_match_we = Signal()
        self.o_match_space = Signal()

        # read event from fifo
        self.o_event = Signal(31)
        self.o_event_valid = Signal()
        self.i_event_re = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.match_fifo = match_fifo = self.match_fifo
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

            self.o_event.eq(event_fifo.r_data),
            self.o_event_valid.eq(event_fifo.r_rdy),
            event_fifo.r_en.eq(self.i_event_re),
        ]

        return m
