# an SNES poker for Boneless

from nmigen import *
from nmigen.asserts import Past, Rose, Fell
from nmigen.lib.cdc import FFSynchronizer

from .setreset import *

# Register Map

# 0x0: (W) Latch Ack / (R) Latch
#   Write: writing anything will ack the latch signal and reset to 0
#    Read: the register will be 1 if a latch fall happened or 0 if not

# CONTROLLER BUTTONS: bit 15 to bit 0, 1 if pressed: BYsSudlrAXLR1234

# 0x8: player 1 data 0 buttons
# 0x9: player 1 data 1 buttons
# 0xC: player 2 data 0 buttons
# 0xD: player 2 data 1 buttons

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
        m.d.comb += latched.eq(prev_latch & ~i_latch)
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

        # define the signals that make up the registers
        did_latch = SetReset(m, priority="set")
        m.d.comb += did_latch.set.eq(self.controllers.o_latched)

        # handle the boneless bus.
        read_data = Signal(16) # it expects one cycle of read latency
        m.d.sync += self.o_rdata.eq(read_data)

        with m.If(self.i_re):
            # the only thing to read is latch status
            m.d.comb += read_data.eq(Cat(did_latch.value, 0))

        with m.If(self.i_we):
            with m.Switch(self.i_addr):
                with m.Case(0): # latch ack
                    m.d.comb += did_latch.reset.eq(1)
                with m.Case(0x8):
                    m.d.sync += controllers.i_buttons["p1d0"].eq(self.i_wdata)
                with m.Case(0x9):
                    m.d.sync += controllers.i_buttons["p1d1"].eq(self.i_wdata)
                with m.Case(0xC):
                    m.d.sync += controllers.i_buttons["p2d0"].eq(self.i_wdata)
                with m.Case(0xD):
                    m.d.sync += controllers.i_buttons["p2d1"].eq(self.i_wdata)

        return m
