from nmigen import *
from nmigen.back import verilog

from .core import ChronoFigureCore
from .snes_bus import make_cart_signals

# create the topmost module. it's responsible for setting up the clock.
class Top(Elaboratable):
    def __init__(self):
        # main system clock
        self.i_clock = Signal()

        self.i_config = Signal(32) # configuration word
        self.i_config_addr = Signal(8) # which matcher to apply it to
        self.i_config_we = Signal() # write word to the address

        # connection to the event FIFO
        self.o_event = Signal(31)
        self.o_event_valid = Signal()
        self.i_event_re = Signal() # acknowledge the data

        # version constant output for the get version command
        self.o_gateware_version = Signal(32)

        self.cart_signals = make_cart_signals()
        # expose cart signal named signals to the outside world
        for fi, field in enumerate(self.cart_signals._fields):
            s = Signal(len(self.cart_signals[fi]), name="i_snes_"+field)
            setattr(self, "i_snes_"+field, s)

        self.cfcore = ChronoFigureCore(self.cart_signals)

    def elaborate(self, platform):
        m = Module()

        # hook up the clock source
        m.d.comb += ClockSignal("sync").eq(self.i_clock)
        m.d.comb += ResetSignal("sync").eq(0)

        m.submodules.cfcore = cfcore = self.cfcore

        # hook up the exposed cart signals
        for fi, field in enumerate(self.cart_signals._fields):
            m.d.comb += self.cart_signals[fi].eq(getattr(self, "i_snes_"+field))
        # everything else just gets passed straight through
        for var in dir(self):
            if var == "i_clock" or var.startswith("i_snes_"): continue
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
