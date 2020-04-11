from nmigen import *
from nmigen_boards.icebreaker import *

import argparse

from . import pmod_resources
from ..shell import TASHAShell
from ..shell import ClockSignals, SNESSignals, UARTSignals, MemorySignals
from .spram import SPRAM
from .pll import PLL

# create the build-specific topmost module. it's responsible for setting up the
# platform, hooking up the PLL and clocks, and providing access to the main RAM
class Top(Elaboratable):
    def __init__(self):
        pass

    def elaborate(self, platform):
        # add the tas-specific resources through which the system interfaces to
        # the real world and console
        platform.add_resources(pmod_resources.snes_pmod)
        platform.add_resources(pmod_resources.snes_apu_pmod)

        m = Module()

        # hook up clocks first. we need to snag the clock pin for the PLL before
        # it gets assigned to the default domain
        clk_pin = platform.request(platform.default_clk, dir="-")
        # now we hook it up to the PLL. since we need to give the raw signals,
        # we just use dummy domain names here
        pll = PLL(12, 24.75, clk_pin,
            orig_domain_name="top_sys", # runs at 12MHz source frequency
            pll_domain_name="top_apu", # runs at 24.75MHz output frequency
        )
        m.submodules += pll

        # reset the PLL if the reset button is pressed. its reset is active low!
        reset_button = platform.request("button", 0) # the user button
        m.d.comb += pll.reset.eq(~reset_button)

        global_reset = Signal() # active high reset for everything
        # reset everything if the PLL loses lock or the reset button is pressed
        m.d.comb += global_reset.eq((~pll.pll_lock) | reset_button)

        clock_signals = ClockSignals(
            i_reset=global_reset,
            i_sys_clk_12=ClockSignal("top_sys"),
            i_apu_clk_24p75=ClockSignal("top_apu"),
        )

        # gather up the SNES's signals
        snes_pins = platform.request("snes")
        snes_apu_pins = platform.request("snes_apu", 0,
            xdr={"clock1": 2, "clock2": 2})
        # we have multiple clock outputs since one may not be strong enough
        o_apu_ddr_clk = Signal()
        o_apu_ddr_lo = Signal()
        o_apu_ddr_hi = Signal()
        m.d.comb += [
            snes_apu_pins.clock1.o_clk.eq(o_apu_ddr_clk),
            snes_apu_pins.clock1.o0.eq(o_apu_ddr_lo),
            snes_apu_pins.clock1.o1.eq(o_apu_ddr_hi),
            snes_apu_pins.clock2.o_clk.eq(o_apu_ddr_clk),
            snes_apu_pins.clock2.o0.eq(o_apu_ddr_lo),
            snes_apu_pins.clock2.o1.eq(o_apu_ddr_hi),
        ]

        snes_signals = SNESSignals(
            i_latch=snes_pins.latch,
            i_p1clk=snes_pins.p1clk,
            i_p2clk=snes_pins.p2clk,

            o_p1d0=snes_pins.p1d0,
            o_p1d1=snes_pins.p1d1,
            o_p2d0=snes_pins.p2d0,
            o_p2d1=snes_pins.p2d1,

            o_apu_ddr_clk=o_apu_ddr_clk,
            o_apu_ddr_lo=o_apu_ddr_lo,
            o_apu_ddr_hi=o_apu_ddr_hi,
        )

        # and the UART signals
        uart_pins = platform.request("uart")
        uart_signals = UARTSignals(
            i_rx=uart_pins.rx,
            o_tx=uart_pins.tx,
        )

        # now we need to hook up memory. since the available memories can vary
        # depending on the FPGA, we're just given the bus and we have to put
        # something there. it's no coincidence that the bus is set up precisely
        # for one ice40 SPRAM block. note that we have to create a clock domain
        # based on the provided bus clock
        mem_clock = Signal()
        mem_reset = Signal()
        mem_domain = ClockDomain("top_mem")
        m.domains += mem_domain
        m.d.comb += [
            ClockSignal("top_mem").eq(mem_clock),
            ResetSignal("top_mem").eq(mem_reset), # already synced to clock
        ]

        mem = DomainRenamer("top_mem")(SPRAM())
        m.submodules += mem

        memory_signals = MemorySignals(
            o_clock=mem_clock,
            o_reset = mem_reset,

            o_addr=mem.i_addr,

            o_re=mem.i_re,
            i_rdata=mem.o_data,

            o_we=mem.i_we,
            o_wdata=mem.i_data,
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

# build (and optionally program) the design
parser = argparse.ArgumentParser()
parser.add_argument("-p", "--program", action="store_true",
    help="program the platform with the built design")
args = parser.parse_args()

platform = ICEBreakerPlatform()
platform.build(Top(), do_program=args.program, synth_opts="-abc9")
