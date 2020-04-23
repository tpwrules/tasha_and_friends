# (perhaps excessively) simple timers for boneless. up to 16

NUM_TIMERS = 2

from nmigen import *
from nmigen.asserts import Past, Rose, Fell

from .setreset import *

# Register Map

# 0xn: (R) Timer n status
#    Read: bit  0: 1 if timer ended, 0 otherwise
#   Write:   15-0: timer value. writing resets timer ended flag. timer
#                  decrements every 256 cycles (on another global timer). on
#                  1->0 transition, the end flag gets set.

class Timer(Elaboratable):
    def __init__(self):
        # boneless bus inputs
        self.i_re = Signal()
        self.i_we = Signal()
        self.i_addr = Signal(4)
        self.o_rdata = Signal(16)
        self.i_wdata = Signal(16)

    def elaborate(self, platform):
        m = Module()

        # increments every clock cycle. when the high bit changes, the timers
        # are decremented -> 256 cycle decrement period for them.
        global_counter = Signal(9)
        do_decrement = Signal()
        m.d.sync += [
            global_counter.eq(global_counter+1),
            do_decrement.eq(global_counter[-1] != Past(global_counter)[-1]),
        ]

        # NOT arrays, we don't index them dynamically
        timer_val = tuple(Signal(16) for _ in range(NUM_TIMERS))
        timer_ended = tuple(Signal(1) for _ in range(NUM_TIMERS))
        # decrement timers (before they potentially get written to)
        for ti in range(NUM_TIMERS):
            with m.If((timer_val[ti] > 0) & do_decrement):
                m.d.sync += timer_val[ti].eq(timer_val[ti]-1)
                with m.If(timer_val[ti] == 1):
                    m.d.sync += timer_ended[ti].eq(1)

        # let the timer values be set
        with m.If(self.i_we):
            with m.Switch(self.i_addr):
                for ti in range(NUM_TIMERS):
                    with m.Case(ti):
                        m.d.sync += [
                            timer_val[ti].eq(self.i_wdata),
                            timer_ended[ti].eq(0),
                        ]
                with m.Case():
                    pass

        # and let the end status be read
        read_status = Signal() # bus expects one cycle of read latency
        m.d.sync += self.o_rdata.eq(Cat(read_status, 0))
        with m.If(self.i_re): 
            with m.Switch(self.i_addr):
                for ti in range(NUM_TIMERS):
                    with m.Case(ti):
                        m.d.comb += read_status.eq(timer_ended[ti])
                with m.Case():
                    pass

        return m
