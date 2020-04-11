from nmigen import *
from nmigen.build import *

# connect to PMOD1A
snes_pmod = [
    Resource("snes", 0,
        # inputs from snes
        Subsignal("latch", Pins("4", dir="i", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
        Subsignal("p1clk", Pins("2", dir="i", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
        Subsignal("p2clk", Pins("3", dir="i", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),

        # outputs to snes
        Subsignal("p1d0", Pins("8", dir="o", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
        Subsignal("p1d1", Pins("9", dir="o", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
        Subsignal("p2d0", Pins("10", dir="o", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
        Subsignal("p2d1", Pins("7", dir="o", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),

        Subsignal("test", Pins("1", dir="o", conn=("pmod", 0)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
    )
]

# connect to PMOD1B
snes_apu_pmod = [
    Resource("snes_apu", 0,
        Subsignal("clock1", Pins("4", dir="o", conn=("pmod", 1)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
        Subsignal("clock2", Pins("3", dir="o", conn=("pmod", 1)),
            Attrs(IO_STANDARD="SB_LVCMOS33")),
    )
]
