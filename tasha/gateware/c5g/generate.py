from nmigen import *
from nmigen.back import verilog

import argparse

from ..shell import TASHAShell
from ..shell import ClockSignals, SNESSignals, UARTSignals, MemorySignals

# create the build-specific topmost module. it's responsible for setting up the
# platform, hooking up the PLL and clocks, and providing access to the main RAM
class Top(Elaboratable):
    def __init__(self):
        self.i_reset = Signal()
        self.i_sys_clk_12 = Signal()
        self.i_apu_clk_24p75 = Signal()

        self.i_latch = Signal()
        self.i_p1clk = Signal()
        self.i_p2clk = Signal()

        self.o_p1d0 = Signal()
        self.o_p1d1 = Signal()
        self.o_p2d0 = Signal()
        self.o_p2d1 = Signal()

        self.o_apu_ddr_clk = Signal()
        self.o_apu_ddr_lo = Signal()
        self.o_apu_ddr_hi = Signal()

        self.i_rx = Signal()
        self.o_tx = Signal()

        self.o_mem_clock = Signal()
        self.o_mem_reset = Signal()

        self.o_addr = Signal(15)
        self.o_re = Signal()
        self.i_rdata = Signal(16)
        self.o_we = Signal()
        self.o_wdata = Signal(16)

    def elaborate(self, platform):
        m = Module()

        clock_signals = ClockSignals(
            i_reset=self.i_reset,
            i_sys_clk_12=self.i_sys_clk_12,
            i_apu_clk_24p75=self.i_apu_clk_24p75,
        )

        # signals must be inverted before they enter the SNES, because it also
        # inverts them. our interface board doesn't either, so we have to do it
        # instead.
        p1d0 = Signal()
        p1d1 = Signal()
        p2d0 = Signal()
        p2d1 = Signal()
        m.d.comb += [
            self.o_p1d0.eq(~p1d0),
            self.o_p1d1.eq(~p1d1),
            self.o_p2d0.eq(~p2d0),
            self.o_p2d1.eq(~p2d1),
        ]

        snes_signals = SNESSignals(
            i_latch=self.i_latch,
            i_p1clk=self.i_p1clk,
            i_p2clk=self.i_p2clk,

            o_p1d0=p1d0,
            o_p1d1=p1d1,
            o_p2d0=p2d0,
            o_p2d1=p2d1,

            o_apu_ddr_clk=self.o_apu_ddr_clk,
            o_apu_ddr_lo=self.o_apu_ddr_lo,
            o_apu_ddr_hi=self.o_apu_ddr_hi,
        )

        uart_signals = UARTSignals(
            i_rx=self.i_rx,
            o_tx=self.o_tx,
        )

        memory_signals = MemorySignals(
            o_clock=self.o_mem_clock,
            o_reset=self.o_mem_reset,

            o_addr=self.o_addr,

            o_re=self.o_re,
            i_rdata=self.i_rdata,

            o_we=self.o_we,
            o_wdata=self.o_wdata,
        )

        # finally we can hook this all up to the system shell
        shell = TASHAShell(
            clock_signals=clock_signals,
            snes_signals=snes_signals,
            uart_signals=uart_signals,
            memory_signals=memory_signals
        )
        m.submodules += shell

        return m

# make all the inputs and outputs ports of the top level module
m = Top()
ports = []
for var in dir(m):
    if var.startswith("i_") or var.startswith("o_"):
        ports.append(getattr(m, var))

# then convert everything to verilog
print(verilog.convert(m, "tasha_sys_c5g", ports=ports))
