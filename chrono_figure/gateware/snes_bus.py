from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from collections import namedtuple

# define the SNES cart interface. all inputs because we just watch
SNESCartSignals = namedtuple("SNESCartSignals", [
    # 8 bit data bus
    "data",

    # 24 bit "A" address bus
    "addr",
    # active-low read and write signals (with unknown timing!)
    "rd",
    "wr",

    # 8 bit "B" address bus
    "periph_addr",
    # active-low read and write signals (still with unknown timing!)
    "pard",
    "pawr",

    # master 21.477272MHz clock
    "clock",
])

# return a filled out SNESCartSignals with all the Signal()s inside
def make_cart_signals():
    return SNESCartSignals(
        data=Signal(8, name="data"),
        
        addr=Signal(24, name="addr"),
        rd=Signal(name="rd"),
        wr=Signal(name="wr"),

        periph_addr=Signal(8, name="periph_addr"),
        pard=Signal(name="pard"),
        pawr=Signal(name="pawr"),

        clock=Signal(name="clock"),
    )

# THE SNES CART BUS: facts
#  1. One "cycle" below refers to 1 96MHz period, the frequency the SD2SNES
#     samples the bus at and that all this logic is clocked at.
#  2. One "bus cycle" refers to 1 21.47727MHz period, the frequency the SNES
#     master oscillator runs at (or 21.28137MHz for PAL). This clock is
#     available on the cart bus's "clock" pin. The bus is asynchronous.
#  3. The A bus is 24 bits and used by the CPU to access RAM and ROM. Its
#     address is available on "addr". /RD and /WR are asserted active low when
#     the CPU wants to read or write an address on the A bus.
#  4. The B bus is 8 bits and used by the CPU to access peripherals. Its address
#     is available on "periph_addr". /PARD and /PAWR are asserted active low
#     when the CPU wants to read or write an address on the B bus.
#  5. The data bus is 8 bits, bidirectional, and common to both A and B buses.
#  6. The CPU only accesses one bus at a time, unless doing DMA.
#  7. DMA can only transfer from the A bus to the B bus, or vice versa.
#  8. During DMA, both /RD and /PAWR are asserted for an A->B transfer, or /WR 
#     and /PARD are asserted for a B->A transfer.
#  9. The CPU can access memory at three different speeds, which dictates the
#     period of /RD, /WR, /PARD, and /PAWR.
#  9. The period is 6 bus cycles (3.58MHz) for FastROM and I/O ports.
# 10. The period is 8 bus cycles (2.68MHz) for SlowROM, RAM, and DMA.
# 11. The period is 12 bus cycles (1.79MHz) for joypad I/O ports.

# THE SNES CART BUS: observations gained from bus trace mode
#  1. Address is valid when /RD is asserted.
#  2. Data is valid when /RD is deasserted.
#  3. Address becomes invalid around the cycle /RD is deasserted.
#  4. B bus address equals the low 8 bits of the A bus address when the CPU is
#     not performing DMA (but lags by a cycle or so).
#  5. /PARD equals /RD when the CPU accesses the B bus and isn't performing DMA.
#  6. /RD and /PAWR (or vice versa?) are asserted on the same cycle during DMA.
#  7. /PAWR (and /PARD?) is deasserted ~3 cycles before /RD during DMA.
#  8. /RD period is ~27 cycles at 3.58MHz bus speed and ~36 at 2.68MHz.
#  9. /RD low time is ~13 cycles at 3.58MHz bus speed and ~22 at 2.68MHz.
# 10. /RD is asserted 1 or 2 cycles after the clock goes high.
# 11. /RD is deasserted 0 or 1 cycle after the clock goes high.
# 12. /WR and /PAWR behave the same as /RD and /PARD.

# translate and clean up the SNES bus signals to what we need. currently it does
# not monitor the B bus, but because accesses are mirrored on the A bus when DMA
# is not active, the only unknown variable is the B bus address accessed by DMA.
class SNESBus(Elaboratable):
    def __init__(self, cart_signals):
        self.cart_signals = cart_signals

        # 1 when the rest of the bus signals are valid
        self.o_valid = Signal()
        self.o_addr = Signal(24)
        self.o_data = Signal(8)
        self.o_write = Signal() # 1 if access is write or 0 if read
        # raw cart signals for bus trace mode
        self.o_cart_signals = make_cart_signals()

        # number of SNES master clock cycles since the sd2snes was powered on
        self.o_cycle_count = Signal(32)

    def elaborate(self, platform):
        m = Module()

        cart = []
        # synchronize the quite asynchronous SNES bus signals to our domain.
        # this seems to work okay, but the main sd2snes uses more sophisticated
        # techniques to determine the bus state and we may have to steal some.
        cart = make_cart_signals()
        m.submodules.bus_sync = \
            FFSynchronizer(Cat(*self.cart_signals), Cat(*cart))

        # keep track of the SNES bus clock cycle so the system can time events.
        # because we sample the counter when /RD is deasserted, which happens on
        # or slightly after the rising edge, we increment it on the falling edge
        # so the counter value will be consistent.
        cycle_counter = Signal(32)
        last_clock = Signal()
        m.d.sync += last_clock.eq(cart.clock)
        with m.If(last_clock & ~cart.clock):
            m.d.sync += cycle_counter.eq(cycle_counter + 1)
        m.d.comb += self.o_cycle_count.eq(cycle_counter)

        # because /RD and /WR behave the same and only one is ever asserted, we
        # can just AND them together and monitor both.
        bus_was_asserted = Signal()
        bus_is_asserted = Signal()
        m.d.comb += bus_is_asserted.eq(~(cart.rd & cart.wr))
        m.d.sync += bus_was_asserted.eq(bus_is_asserted)

        # though we need to sample the data when /RD is deasserted, the address
        # is not valid at that time. we could sample the address when /RD is
        # asserted, but that would leave ~14 cycles from deassertion (when the
        # access is valid) until assertion (when the sampled address is
        # overwritten). this isn't enough time for the matchers to work, so we
        # sample the address 7 cycles after /RD is asserted, leaving ~21 cycles.
        sample_counter = Signal(3)
        bus_addr = Signal(24)
        is_write = Signal()
        with m.If(~bus_was_asserted & bus_is_asserted):
            m.d.sync += sample_counter.eq(7)
        with m.If(sample_counter > 0):
            m.d.sync += sample_counter.eq(sample_counter - 1)
            with m.If(sample_counter - 1 == 0):
                m.d.sync += [
                    bus_addr.eq(cart.addr),
                    is_write.eq(cart.rd), # /RD == WR
                ]

        m.d.comb += [
            self.o_valid.eq(bus_was_asserted & ~bus_is_asserted),
            self.o_data.eq(cart.data), # now valid on deassertion
            self.o_addr.eq(bus_addr), # both valid from earlier sampling
            self.o_write.eq(is_write),
        ]

        return m
