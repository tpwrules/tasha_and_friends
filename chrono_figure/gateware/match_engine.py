from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .multimatcher import MultiMatcher
from .snes_bus import make_cart_signals

from collections import namedtuple

# define all the data that results from a match
MatchInfo = namedtuple("MatchInfo", [
    "match_type", # what type of match happened
    "cycle_count", # cycle it happened
    "addr", # what address was matched
    "data", # what data was on the bus
])

# return a filled out MatchInfo with all the Signal()s inside
def make_match_info():
    return MatchInfo(
        match_type=Signal(MATCH_TYPE_BITS, name="match_type"),
        cycle_count=Signal(32, name="cycle_count"),
        addr=Signal(24, name="addr"),
        data=Signal(8, name="data"),
    )

class MatchEngine(Elaboratable):
    def __init__(self):
        # SNES bus signals
        self.i_bus_valid = Signal()
        self.i_bus_addr = Signal(24)
        self.i_bus_data = Signal(8)
        self.i_bus_write = Signal()
        self.i_cycle_count = Signal(32)
        self.i_cart_signals = make_cart_signals()

        # config bus signals
        self.i_config = Signal(32)
        self.i_config_addr = Signal(10)
        self.i_config_we = Signal()

        self.o_match_info = make_match_info()
        self.o_match_valid = Signal()
        self.i_match_re = Signal()
        self.i_reset_match_fifo = Signal()
        self.i_match_bus_trace = Signal()

        self.match_fifo = SyncFIFOBuffered(width=72, depth=256)
        self.multimatcher = MultiMatcher()

    def elaborate(self, platform):
        m = Module()

        m.submodules.match_fifo = match_fifo = \
            ResetInserter(self.i_reset_match_fifo)(self.match_fifo)
        m.submodules.multimatcher = multimatcher = self.multimatcher

        # wire up the multimatcher
        multimatched_type = Signal(MATCH_TYPE_BITS)
        m.d.comb += [
            multimatcher.i_bus_valid.eq(self.i_bus_valid),
            multimatcher.i_bus_addr.eq(self.i_bus_addr),
            multimatcher.i_bus_data.eq(self.i_bus_data),
            multimatcher.i_bus_write.eq(self.i_bus_write),

            multimatcher.i_config.eq(self.i_config),
            multimatcher.i_config_addr.eq(self.i_config_addr),
            multimatcher.i_config_we.eq(self.i_config_we),

            multimatched_type.eq(multimatcher.o_match_type),
        ]

        # the final output. will be 0 if no matchers matched, or the type of
        # that match otherwise.
        matched_type = Signal(MATCH_TYPE_BITS)
        match_valid = Signal()
        match_info = make_match_info()
        m.d.comb += [
            matched_type.eq(multimatched_type),
            match_valid.eq(matched_type != 0),
            match_info.match_type.eq(matched_type),
            # the inputs remain valid until all the matchers finish matching
            match_info.cycle_count.eq(self.i_cycle_count),
            match_info.addr.eq(self.i_bus_addr),
            match_info.data.eq(self.i_bus_data),
        ]

        # put together the match info used when tracing. it's just the raw cart
        # signals arranged to fit the info with little regard for field meanings
        sys_cycle = Signal(11)
        m.d.sync += sys_cycle.eq(sys_cycle + 1)
        trace_match_info = make_match_info()
        cart = self.i_cart_signals
        trace_data = Signal(32)
        m.d.comb += trace_data.eq(Cat(
            sys_cycle, # keep track of system cycle count to measure contiguity
            cart.clock, # track bus clock signal
            cart.rd, cart.wr, cart.pard, cart.pawr, # and async status signals
            cart.periph_addr, # we want to know peripheral address too
            cart.data, # and bus data, packed here to be sent with the rest
        ))
        m.d.comb += [
            trace_match_info.match_type.eq(-1), # always the highest type
            # we pack extra data into the cycle count so it can be sent in one
            # word. of course this badly confuses the timers...
            trace_match_info.cycle_count.eq(trace_data),
            trace_match_info.addr.eq(cart.addr),
            trace_match_info.data.eq(self.i_bus_data), # avoid the mux
        ]

        # put the match into a FIFO so it can be processed at the core's leisure
        assert(len(Cat(*match_info)) <= 72) # ensure it can fit
        m.d.comb += [
            match_fifo.w_data.eq(Mux(self.i_match_bus_trace,
                Cat(*trace_match_info), Cat(*match_info))),
            match_fifo.w_en.eq(match_valid | self.i_match_bus_trace),

            Cat(*self.o_match_info).eq(match_fifo.r_data),
            self.o_match_valid.eq(match_fifo.r_rdy),
            match_fifo.r_en.eq(self.i_match_re),
        ]

        return m
