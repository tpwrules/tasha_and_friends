# an SNES poker for Boneless

from nmigen import *
from nmigen.asserts import Past, Rose, Fell
from nmigen.lib.cdc import FFSynchronizer

from .setreset import *
from .apu_clockgen import APUClockgen
from .apu_calc import calculate_counter

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

# APU frequency adjustment registers. Consult apu_clockgen.py for the complete
# explanation and limitations of the registers.

# 0x2: (W) APU frequency adjust (basic)
#   Write:   15-0: middle 16 bits of the 24 bit APU frequency counter
#   This register controls the middle bits of the frequency counter to provide a
#   reasonable range of adjustment. In most cases, register 3 can be left alone
#   and only register 2 needs to be updated. When a latch event occurs, this
#   register is transferred to the APU clock generator.

# 0x3: (W) APU frequency adjust (advanced)
#   Write: bit 15: output polarity (0 = drop high pulses, 1 = drop low pulses)
#          bit 14: jitter mode (0 = advance LFSR every cycle, 1 = every drop)
#            10-8: jitter amount (0 = no, 7 = up to 127 cycles)
#             7-4: high 4 bits of frequency counter (for very low frequencies)
#             3-0: low 4 bits of frequency counter (for fine frequency adjust)
#   This register provides advanced controls for the APU clock generator. In
#   most cases, register 3 can be left alone and only register 2 needs to be
#   updated. When a latch event occurs, this register is transferred to the APU
#   clock generator.

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
        self.apu_clockgen = APUClockgen()
    
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

        # drive the APU clock
        apu_clockgen = DomainRenamer("apu")(self.apu_clockgen)
        m.submodules.apu_clockgen = apu_clockgen
        # we default to the stock BSNES frequency since that's theoretically
        # what the TASes are designed for (even though it's not that useful)

        # APU frequency registers set on the boneless bus
        ar_counter = Signal(24, reset=calculate_counter(24.607104)[0])
        ar_jitter = Signal(3)
        ar_jitter_mode = Signal()
        ar_polarity = Signal()

        # current values, latched from registers
        ac_counter = Signal(24, reset=calculate_counter(24.607104)[0])
        ac_jitter = Signal(3)
        ac_jitter_mode = Signal()
        ac_polarity = Signal()

        # latch in new frequency with latch signal
        with m.If(self.controllers.o_latched):
            m.d.sync += [
                ac_counter.eq(ar_counter),
                ac_jitter.eq(ar_jitter),
                ac_jitter_mode.eq(ar_jitter_mode),
                ac_polarity.eq(ar_polarity),
            ]

        m.d.comb += [
            apu_clockgen.i_counter.eq(ac_counter),
            apu_clockgen.i_jitter.eq(ac_jitter),
            apu_clockgen.i_jitter_mode.eq(ac_jitter_mode),
            apu_clockgen.i_polarity.eq(ac_polarity),

            self.snes_signals.o_apu_ddr_clk.eq(apu_clockgen.o_apu_ddr_clk),
            self.snes_signals.o_apu_ddr_lo.eq(apu_clockgen.o_apu_ddr_lo),
            self.snes_signals.o_apu_ddr_hi.eq(apu_clockgen.o_apu_ddr_hi),
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
                with m.Case(2): # basic APU frequency adjust
                    m.d.sync += ar_counter[4:-4].eq(self.i_wdata)
                with m.Case(3): # advanced APU frequency adjust
                    m.d.sync += [
                        ar_polarity.eq(self.i_wdata[15]),
                        ar_jitter_mode.eq(self.i_wdata[14]),
                        ar_jitter.eq(self.i_wdata[8:11]),
                        ar_counter[-4:].eq(self.i_wdata[4:8]),
                        ar_counter[:4].eq(self.i_wdata[0:4]),
                    ]
                with m.Case(0x4):
                    m.d.sync += controllers.i_buttons["p1d0"].eq(self.i_wdata)
                with m.Case(0x5):
                    m.d.sync += controllers.i_buttons["p1d1"].eq(self.i_wdata)
                with m.Case(0x6):
                    m.d.sync += controllers.i_buttons["p2d0"].eq(self.i_wdata)
                with m.Case(0x7):
                    m.d.sync += controllers.i_buttons["p2d1"].eq(self.i_wdata)

        return m
