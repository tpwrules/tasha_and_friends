# interface between the core and the platform-specific stuff
from nmigen import *
from nmigen.lib.cdc import ResetSynchronizer

from collections import namedtuple

from .core import TASHACore

# define the signals we need access to so the platforms can give them to us
ClockSignals = namedtuple("ClockSignals", [
    "i_reset", # reset signal, ACTIVE HIGH, asynchronous

    "i_sys_clk_12", # main system clock, expected to be 12MHz
    "i_apu_clk_24p75", # APU drive clock, expected to be 24.75MHz
])

SNESSignals = namedtuple("SNESSignals", [
    # controller signals
    "i_latch", # latch input from console
    "i_p1clk", # clock for player 1 controller
    "i_p2clk", # clock for player 2 controller

    # controller loopback signals. 1 the cycle after one of the above signals
    # was detected and 0 otherwise
    "o_latched",
    "o_p1clked",
    "o_p2clked",

    "o_p1d0", # player 1 controller data line 0
    "o_p1d1", #                          line 1
    "o_p2d0", # player 2                 line 0
    "o_p2d1", #                          line 1

    # APU clock drive signals, for use with a DDR pin
    "o_apu_ddr_clk", # clock for DDR output
    "o_apu_ddr_lo", # signal when clock is low
    "o_apu_ddr_hi", # signal when clock is high
])

UARTSignals = namedtuple("UARTSignals", [
    "i_rx",
    "o_tx",
])

MemorySignals = namedtuple("MemorySignals", [
    "o_clock", # clock that the other signals are synchronous to
    "o_reset", # active high reset synchronous to the clock,

    "o_addr", # address, 15 bits wide

    "o_re", # when asserted, data must be available next cycle
    "i_rdata", # read data, 16 bits wide

    "o_we", # when asserted, data must be written this cycle
    "o_wdata", # data to write, 16 bits wide
])

# the shell hooks up the clocks and isolates the core from the outside world
class TASHAShell(Elaboratable):
    def __init__(self, clock_signals, snes_signals,
            uart_signals, memory_signals):

        self._in_clock_signals = clock_signals
        self._in_snes_signals = snes_signals
        self._in_uart_signals = uart_signals
        self._in_memory_signals = memory_signals

    def elaborate(self, platform):
        m = Module()

        # copy all the signals to validate them and make sure we (as a system)
        # have a version we can do whatever with and is just connected to the
        # outside world
        def copy_signals(signals):
            copied = []
            for fi, field in enumerate(signals._fields):
                outside_signal = signals[fi]
                if not isinstance(outside_signal, Value):
                    raise TypeError("{} must be a Value, not {!r}".format(
                        field, type(outside_signal)))
                our_signal = Signal(len(outside_signal), name=field)
                if field.startswith("i_"):
                    m.d.comb += our_signal.eq(outside_signal)
                else:
                    m.d.comb += outside_signal.eq(our_signal)
                copied.append(our_signal)
            return signals._make(copied)

        clock_signals = copy_signals(self._in_clock_signals)
        snes_signals = copy_signals(self._in_snes_signals)
        uart_signals = copy_signals(self._in_uart_signals)
        memory_signals = copy_signals(self._in_memory_signals)

        # now we can give all the signals to the core
        core = TASHACore(
            snes_signals=snes_signals,
            uart_signals=uart_signals,
            memory_signals=memory_signals,
        )
        m.submodules += core

        # wire up the clocks to the actual clock domains. we do it here because
        # the different platforms have different ways of giving us clocks
        sync_domain = ClockDomain("sync")
        apu_domain = ClockDomain("apu")
        m.domains += [sync_domain, apu_domain]
        m.d.comb += [
            ClockSignal("sync").eq(clock_signals.i_sys_clk_12),
            ClockSignal("apu").eq(clock_signals.i_apu_clk_24p75),
        ]
        # hook up reset signals too. the system can request its own reset, so we
        # have to incorporate that here.
        do_reset = Signal()
        m.d.comb += do_reset.eq(clock_signals.i_reset | core.o_reset_req)
        # synchronize the various resets to the clock domains. we use a lot of
        # stages to ensure that nothing weird happens when the system tries to
        # reset itself
        m.submodules += ResetSynchronizer(do_reset, domain="sync", stages=4)
        m.submodules += ResetSynchronizer(do_reset, domain="apu", stages=4)

        return m
