from nmigen import *

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .matcher import Matcher

from collections import namedtuple

# define all the data that results from a match
MatchInfo = namedtuple("MatchInfo", [
    "match_type", # what type of match happened
    "cycle_count", # cycle it happened
])

# return a filled out MatchInfo with all the Signal()s inside
def make_match_info():
    return MatchInfo(
        match_type=Signal(MATCH_TYPE_BITS, name="match_type"),
        cycle_count=Signal(32, name="cycle_count"),
    )

class MatchEngine(Elaboratable):
    def __init__(self):
        # SNES bus signals
        self.i_bus_valid = Signal()
        self.i_bus_addr = Signal(24)
        self.i_cycle_count = Signal(32)

        # config bus signals
        self.i_config = Signal(32)
        self.i_config_addr = Signal(8)
        self.i_config_we = Signal()

        self.o_match_info = make_match_info()
        self.o_match_valid = Signal()

    def elaborate(self, platform):
        m = Module()

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
        mb_valid = Signal()
        m.d.sync += mb_valid.eq(self.i_bus_valid)
        with m.If(self.i_bus_valid):
            m.d.sync += mb_addr.eq(self.i_bus_addr)
        m.d.sync += [
            mb_addr.eq(self.i_bus_addr),
            mb_valid.eq(self.i_bus_valid),
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
        m.d.comb += [
            self.o_match_info.match_type.eq(matched_type),
            self.o_match_info.cycle_count.eq(self.i_cycle_count),
            self.o_match_valid.eq(matched_type != 0),
        ]

        return m
