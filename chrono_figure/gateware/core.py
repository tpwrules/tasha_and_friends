from nmigen import *
from nmigen.lib.cdc import FFSynchronizer
from nmigen.back import verilog

import types

# will probably always be manually incremented because it's related to the
# modules in the sd2snes and its firmware as well
GATEWARE_VERSION = 1

class ChronoFigureCore(Elaboratable):
    def __init__(self):
        # the snes bus inputs
        self.i_snes_addr = Signal(24)
        self.i_snes_periph_addr = Signal(8)
        self.i_snes_rd = Signal()
        self.i_snes_wr = Signal()
        self.i_snes_pard = Signal()
        self.i_snes_pawr = Signal()
        self.i_snes_clock = Signal()
        self.i_snes_reset = Signal()

        # version constant output for the get version command
        self.o_gateware_version = Const(GATEWARE_VERSION, 32)

    def elaborate(self, platform):
        m = Module()

        b = types.SimpleNamespace()
        # synchronize the quite asynchronous SNES bus signals to our domain.
        # this seems to work okay, but the main sd2snes uses more sophisticated
        # techniques to determine the bus state and we may have to steal some.
        for name in dir(self):
            if not name.startswith("i_snes_"): continue
            var = getattr(self, name)
            sync_var = Signal(len(var))
            m.submodules["ffsync_"+name] = FFSynchronizer(var, sync_var)
            setattr(b, name[len("i_snes_"):], sync_var)

        return m
