from nmigen import *
from nmigen.back import verilog

from .core import ChronoFigureCore

# create the topmost module. it's responsible for setting up the clock.
class Top(Elaboratable):
    def __init__(self):
        # main system clock
        self.i_clock = Signal()

        # the snes bus inputs
        self.i_snes_addr = Signal(24)
        self.i_snes_periph_addr = Signal(8)
        self.i_snes_rd = Signal()
        self.i_snes_wr = Signal()
        self.i_snes_pard = Signal()
        self.i_snes_pawr = Signal()
        self.i_snes_clock = Signal()
        self.i_snes_reset = Signal() # pulses high right after reset ends

        self.i_config = Signal(32) # configuration word
        self.i_config_addr = Signal(8) # which matcher to apply it to
        self.i_config_we = Signal() # write word to the address

        # connection to the event FIFO
        self.o_event = Signal(31)
        self.o_event_valid = Signal()
        self.i_event_re = Signal() # acknowledge the data

        # version constant output for the get version command
        self.o_gateware_version = Signal(32)

        self.cfcore = ChronoFigureCore()

    def elaborate(self, platform):
        m = Module()

        # hook up the clock source
        m.d.comb += ClockSignal("sync").eq(self.i_clock)
        m.d.comb += ResetSignal("sync").eq(0)

        m.submodules.cfcore = cfcore = self.cfcore

        # everything else just gets passed straight through
        for var in dir(self):
            if var == "i_clock": continue
            if var.startswith("i_"):
                m.d.comb += getattr(cfcore, var).eq(getattr(self, var))
            elif var.startswith("o_"):
                m.d.comb += getattr(self, var).eq(getattr(cfcore, var))

        return m

# make all the inputs and outputs ports of the top level module
m = Top()
ports = []
for var in dir(m):
    if var.startswith("i_") or var.startswith("o_"):
        ports.append(getattr(m, var))

# then convert everything to verilog
print(verilog.convert(m, "chrono_figure_sys", ports=ports))
