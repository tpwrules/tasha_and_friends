# an SNES poker for Boneless

from nmigen import *
from nmigen.asserts import Past, Rose, Fell
from nmigen.lib.cdc import FFSynchronizer

from .setreset import *

# Register Map

# 0x0: (R) Did Latch / (W) Force Latch
#    Read: bit  0: 1 if a latch event occurred since acknowledge, 0 if not
#   Write:   15-0: write anything to force a latch event
#   A latch event is forced by setting the latch line to 0 for one cycle. This
#   caues a falling edge, if the console is not already holding it low. If it
#   is, then the latch force has no effect.

# 0x1: (R) Missed Latch & Acknowledge
#    Read: bit  0: 1 if a latch event was missed, 0 if not
#   A latch event is considered "missed" if it occurred while Did Latch above
#   was 1. Reading this register acknowledges the latch by clearing both Did
#   Latch and Missed Latch.


# CONTROLLER BUTTON REGISTERS: bit 15 to bit 0, 1 if pressed: BYsSudlrAXLR1234
# 0x4: player 1 data 0 buttons
# 0x5: player 1 data 1 buttons
# 0x6: player 2 data 0 buttons
# 0x7: player 2 data 1 buttons
# When a latch event occurs, these registers are transferred to the output shift
# registers so the console can shift the data out.

# drive one controller data line. really just a 16 bit shift register.
class DataLineDriver(Elaboratable):
    def __init__(self):
        # controllers were latched: load i_buttons into shift registers
        self.i_latched = Signal()
        # clock: on rising edge, shift register << 1
        self.i_clock = Signal()
        # the buttons to latch in. they go MSB first
        self.i_buttons = Signal(16)

        # data signal to the SNES
        self.o_data = Signal()

    def elaborate(self, platform):
        m = Module()

        # the data we're actually shifting out
        reg = Signal(16)
        # the high bit of which is the serial output
        m.d.comb += self.o_data.eq(reg[-1])

        prev_clock = Signal()
        m.d.sync += prev_clock.eq(self.i_clock)

        with m.If(self.i_latched):
            m.d.sync += reg.eq(self.i_buttons)
        with m.Elif(~prev_clock & self.i_clock):
            # 1s get output once all the buttons are done
            m.d.sync += reg.eq((reg << 1) | 1)

        return m

# pretend to be the SNES controllers
class Controllers(Elaboratable):
    def __init__(self, snes_signals):
        self.snes_signals = snes_signals

        # button inputs for the four data lines. these are transferred to the
        # shift registers the cycle that "latched" goes high.
        self.i_buttons = {
            "p1d0": Signal(16),
            "p1d1": Signal(16),
            "p2d0": Signal(16),
            "p2d1": Signal(16),
        }

        self.i_force_latch = Signal() # pretend a latch occurred
        # latch line fell this cycle (and buttons will be transferred)
        self.o_latched = Signal()

        # make drivers for each controller data line
        self.drivers = {n: DataLineDriver() for n in self.i_buttons.keys()}

    def elaborate(self, platform):
        m = Module()
        snes_signals = self.snes_signals

        # sync input pins because they're attached to arbitrary external logic
        # with an unknown clock
        i_latch = Signal()
        i_p1clk = Signal()
        i_p2clk = Signal()

        m.submodules += FFSynchronizer(snes_signals.i_latch, i_latch)
        m.submodules += FFSynchronizer(snes_signals.i_p1clk, i_p1clk)
        m.submodules += FFSynchronizer(snes_signals.i_p2clk, i_p2clk)

        # detect the latch falling edge so we can prepare appropriately
        latched = Signal()
        prev_latch = Signal()
        m.d.sync += prev_latch.eq(i_latch)
        m.d.comb += latched.eq(prev_latch & ~i_latch & ~self.i_force_latch)
        # tell others the latch status
        m.d.comb += self.o_latched.eq(latched)

        # hook up the drivers
        for line_name in self.i_buttons.keys():
            i_buttons = self.i_buttons[line_name]
            driver = self.drivers[line_name]
            m.d.comb += [
                driver.i_latched.eq(latched),
                driver.i_buttons.eq(i_buttons),
                getattr(snes_signals, "o_"+line_name).eq(driver.o_data),
            ]
            if line_name.startswith("p1"):
                m.d.comb += driver.i_clock.eq(i_p1clk)
            else:
                m.d.comb += driver.i_clock.eq(i_p2clk)

            m.submodules[line_name] = driver

        return m


class SNES(Elaboratable):
    def __init__(self, snes_signals):
        self.snes_signals = snes_signals

        # boneless bus inputs
        self.i_re = Signal()
        self.i_we = Signal()
        self.i_addr = Signal(4)
        self.o_rdata = Signal(16)
        self.i_wdata = Signal(16)

        self.controllers = Controllers(self.snes_signals)
    
    def elaborate(self, platform):
        m = Module()
        m.submodules.controllers = controllers = self.controllers

        # did_latch is priority set so that the SNES can always make sure its
        # latch gets recognized. missed_latch is priority reset, so that if they
        # get acknowledged at the same time a latch happens, it doesn't get
        # counted as a missed latch.
        did_latch = SetReset(m, priority="set")
        missed_latch = SetReset(m, priority="reset")

        m.d.comb += [
            did_latch.set.eq(self.controllers.o_latched),
            missed_latch.set.eq(did_latch.value & self.controllers.o_latched),
        ]

        # handle the boneless bus.
        read_data = Signal() # it expects one cycle of read latency
        m.d.sync += self.o_rdata.eq(Cat(read_data, 0))

        with m.If(self.i_re):
            with m.Switch(self.i_addr[:1]):
                with m.Case(0):
                    m.d.comb += read_data.eq(did_latch.value)
                with m.Case(1):
                    m.d.comb += [
                        # say if we missed the latch
                        read_data.eq(missed_latch.value),
                        # and reset the status
                        did_latch.reset.eq(1),
                        missed_latch.reset.eq(1),
                    ]

        with m.If(self.i_we):
            with m.Switch(self.i_addr[:3]):
                with m.Case(0): # force a latch
                    m.d.comb += controllers.i_force_latch.eq(1)
                with m.Case(0x4):
                    m.d.sync += controllers.i_buttons["p1d0"].eq(self.i_wdata)
                with m.Case(0x5):
                    m.d.sync += controllers.i_buttons["p1d1"].eq(self.i_wdata)
                with m.Case(0x6):
                    m.d.sync += controllers.i_buttons["p2d0"].eq(self.i_wdata)
                with m.Case(0x7):
                    m.d.sync += controllers.i_buttons["p2d1"].eq(self.i_wdata)

        return m
