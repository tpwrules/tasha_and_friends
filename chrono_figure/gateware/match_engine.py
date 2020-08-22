from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .matcher import Matcher

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
        self.i_cycle_count = Signal(32)

        # config bus signals
        self.i_config = Signal(32)
        self.i_config_addr = Signal(8)
        self.i_config_we = Signal()

        self.o_match_info = make_match_info()
        self.o_match_valid = Signal()
        self.i_match_re = Signal()

        self.match_fifo = SyncFIFOBuffered(width=72, depth=256)

    def elaborate(self, platform):
        m = Module()

        m.submodules.match_fifo = match_fifo = self.match_fifo

        # convert 32 bit config word into four 8 bit writes
        mb_config_data = Signal(8)
        mb_config_addr = Signal(MATCHER_BITS)
        mb_config_we = Signal(4) # one line per byte
        config_tmp = Signal(32)
        with m.FSM("IDLE"):
            with m.State("IDLE"):
                # latch current config input
                m.d.sync += [
                    mb_config_we.eq(0),
                    config_tmp.eq(self.i_config),
                    mb_config_addr.eq(self.i_config_addr),
                ]
                with m.If(self.i_config_we):
                    # when write enable is asserted, we will write what we latch
                    # this cycle over the next four
                    m.next = "WB0"

            for byte_i in range(4):
                with m.State("WB{}".format(byte_i)):
                    m.d.sync += [
                        mb_config_we.eq(1<<byte_i),
                        mb_config_data.eq(config_tmp[byte_i*8:(byte_i+1)*8]),
                    ]
                    m.next = "WB{}".format(byte_i+1) if byte_i < 3 else "IDLE"

        # buffer the matcher input signals to ensure the best timing
        mb_addr = Signal(24)
        mb_data = Signal(8)
        mb_valid = Signal()
        m.d.sync += mb_valid.eq(self.i_bus_valid)
        with m.If(self.i_bus_valid):
            m.d.sync += [
                mb_addr.eq(self.i_bus_addr),
                mb_data.eq(self.i_bus_data),
            ]

        # wire up all the matchers
        matcher_results = []
        for matcher_num in range(NUM_MATCHERS):
            matcher = Matcher()
            m.submodules["matcher_{}".format(matcher_num)] = matcher
            m.d.comb += [
                matcher.i_snes_addr.eq(mb_addr),
                matcher.i_snes_rd.eq(mb_valid),

                matcher.i_config_data.eq(mb_config_data),
                matcher.i_config_we.eq(Mux(mb_config_addr == matcher_num,
                    mb_config_we, 0)),
            ]
            matcher_results.append(matcher.o_match_type)

        # OR all the results together in a massive tree. 4 at a time
        # theoretically will use one LUT4?
        to_or = matcher_results
        ored = []
        while len(to_or) > 1:
            while len(to_or) > 0:
                expr = to_or.pop()
                for _ in range(min(3, len(to_or))): # OR in three more
                    expr = expr | to_or.pop()
                s = Signal(MATCH_TYPE_BITS)
                m.d.sync += s.eq(expr)
                ored.append(s)
            to_or = ored
            ored = []

        # the final output. will be 0 if no matchers matched, or the type of
        # that match otherwise.
        matched_type = to_or[0]
        match_valid = Signal()
        match_info = make_match_info()
        m.d.comb += [
            match_valid.eq(matched_type != 0),
            match_info.match_type.eq(matched_type),
            match_info.cycle_count.eq(self.i_cycle_count),
            # there should be enough timing leeway that there won't be another
            # bus transaction before the match is finished processing? maybe?
            match_info.addr.eq(mb_addr),
            match_info.data.eq(mb_data),
        ]

        # put the match into a FIFO so it can be processed at the core's leisure
        assert(len(Cat(*match_info)) <= 72) # ensure it can fit
        m.d.comb += [
            match_fifo.w_data.eq(Cat(*match_info)),
            match_fifo.w_en.eq(match_valid),

            Cat(*self.o_match_info).eq(match_fifo.r_data),
            self.o_match_valid.eq(match_fifo.r_rdy),
            match_fifo.r_en.eq(self.i_match_re),
        ]

        return m
