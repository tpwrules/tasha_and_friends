from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.sim.pysim import Simulator, Delay

from ..eventuator import Eventuator
from .. import widths
from ...match_info import *
from ...match_engine import make_match_info

class SimTop:
    def __init__(self):
        self.event_fifo = SyncFIFOBuffered(width=31, depth=128)

        self.eventuator = Eventuator()
        self.ev_prg_mem = Memory(
            width=widths.INSN_WIDTH, depth=1024, init=[0])
        self.ev_reg_mem = Memory(
            width=widths.DATA_WIDTH, depth=256)

    def simulate(self, vcd_out):
        m = Module()

        m.submodules.event_fifo = event_fifo = self.event_fifo

        m.submodules.eventuator = eventuator = self.eventuator
        m.submodules.ev_prg_rd = ev_prg_rd = self.ev_prg_mem.read_port(
            transparent=False)
        m.submodules.ev_prg_wr = ev_prg_wr = self.ev_prg_mem.write_port()
        m.submodules.ev_reg_rd = ev_reg_rd = self.ev_reg_mem.read_port(
            transparent=False)
        m.submodules.ev_reg_wr = ev_reg_wr = self.ev_reg_mem.write_port()

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

        sim_match_info = make_match_info()
        sim_match_valid = Signal()
        sim_match_re = Signal()

        # hook up the eventuator's inputs and outputs
        m.d.comb += [
            Cat(*eventuator.i_match_info).eq(Cat(*sim_match_info)),
            eventuator.i_match_valid.eq(sim_match_valid),
            sim_match_re.eq(eventuator.o_match_re),

            event_fifo.w_data.eq(eventuator.o_event),
            event_fifo.w_en.eq(eventuator.o_event_valid),
            eventuator.i_event_space.eq(event_fifo.w_rdy),
        ]

        sim = Simulator(m)
        sim.add_clock(1/96e6, domain="sync")

        def main_proc():
            yield sim_match_info.match_type.eq(MATCH_TYPE_RESET)
            yield sim_match_valid.eq(1)
            yield
            yield sim_match_valid.eq(0)
            for x in range(10): yield
            yield sim_match_info.match_type.eq(MATCH_TYPE_NMI)
            yield sim_match_valid.eq(1)
            yield
            yield sim_match_valid.eq(0)

        sim.add_sync_process(main_proc, domain="sync")

        gtkw_out = str(vcd_out).replace(".vcd", ".gtkw")
        with sim.write_vcd(str(vcd_out), gtkw_out, traces=[]):
            sim.run_until(1e-6, run_passive=True)

if __name__ == "__main__":
    import sys
    import pathlib

    st = SimTop()
    vcd_path = pathlib.Path(sys.argv[1])
    vcd_dir = vcd_path.parent.resolve(strict=True)
    vcd_path = vcd_dir/vcd_path.name
    st.simulate(vcd_path)
