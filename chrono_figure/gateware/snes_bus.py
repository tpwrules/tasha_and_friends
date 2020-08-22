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

# translate and clean up the SNES bus signals to what we need
class SNESBus(Elaboratable):
    def __init__(self, cart_signals):
        self.cart_signals = cart_signals

        # 1 when the rest of the bus signals are valid
        self.o_valid = Signal()
        # for now we can only pick up reads so there's no access type data
        self.o_addr = Signal(24)
        self.o_data = Signal(8)

        # number of SNES master clock cycles since the sd2snes was powered on
        self.o_cycle_count = Signal(32)

    def elaborate(self, platform):
        m = Module()

        cart = []
        # synchronize the quite asynchronous SNES bus signals to our domain.
        # this seems to work okay, but the main sd2snes uses more sophisticated
        # techniques to determine the bus state and we may have to steal some.
        for fi, field in enumerate(self.cart_signals._fields):
            cart_signal = self.cart_signals[fi]
            sync_signal = Signal(len(cart_signal), name=field)
            m.submodules["ffsync_"+field] = \
                FFSynchronizer(cart_signal, sync_signal)
            cart.append(sync_signal)
        cart = self.cart_signals._make(cart)

        # keep track of the SNES clock cycle so the system can time events
        cycle_counter = Signal(32)
        last_clock = Signal()
        m.d.sync += last_clock.eq(cart.clock)
        with m.If(~last_clock & cart.clock):
            m.d.sync += cycle_counter.eq(cycle_counter + 1)
        m.d.comb += self.o_cycle_count.eq(cycle_counter)

        # for now we just need to monitor reads, so we look for when the read
        # line is asserted. we assume the address is valid at that point but tbh
        # we're not 100% sure.
        last_rd = Signal()
        snes_read_started = Signal()
        m.d.sync += last_rd.eq(cart.rd)
        m.d.comb += snes_read_started.eq(last_rd & ~cart.rd)

        m.d.comb += [
            self.o_valid.eq(snes_read_started),
            self.o_addr.eq(cart.addr),
            self.o_data.eq(cart.data),
        ]

        return m
