from nmigen import *
from nmigen.lib.cdc import FFSynchronizer
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.back import verilog

import types

# will probably always be manually incremented because it's related to the
# modules in the sd2snes and its firmware as well
GATEWARE_VERSION = 4

# all the types of matches
MATCH_TYPE_NONE = 0
MATCH_TYPE_RESET = 1
MATCH_TYPE_NMI = 2
MATCH_TYPE_WAIT_START = 3
MATCH_TYPE_WAIT_END = 4

MATCH_TYPE_BITS = 3 # number of bits required to represent the above (max 8)

NUM_MATCHERS = 64 # how many match engines are there?
MATCHER_BITS = 6 # number of bits required to represent the above (max 8)

class Matcher(Elaboratable):
    def __init__(self):
        self.i_snes_addr = Signal(24) # address the snes is accessing
        self.i_snes_rd = Signal() # 1 the cycle the snes starts reading

        # configuration word to set type and address
        self.i_config = Signal(32)
        self.i_config_we = Signal()

        self.o_match_type = Signal(MATCH_TYPE_BITS)

    def elaborate(self, platform):
        m = Module()

        match_addr = Signal(24)
        match_type = Signal(MATCH_TYPE_BITS)

        with m.If(self.i_config_we):
            m.d.sync += [
                match_addr.eq(self.i_config[0:24]),
                match_type.eq(self.i_config[24:24+MATCH_TYPE_BITS]),
            ]

        with m.If(self.i_snes_rd):
            with m.If(self.i_snes_addr == match_addr):
                m.d.comb += self.o_match_type.eq(match_type)

        return m


class ChronoFigureCore(Elaboratable):
    def __init__(self):
        # the snes bus inputs
        self.i_snes_addr = Signal(24)
        self.i_snes_periph_addr = Signal(8)
        self.i_snes_rd = Signal()
        self.i_snes_wr = Signal()
        self.i_snes_pard = Signal()
        self.i_snes_pawr = Signal()
        self.i_snes_clock = Signal()
        # pulses high right after reset ends. not accurate.
        self.i_snes_reset = Signal()

        self.i_config = Signal(32) # configuration word
        self.i_config_addr = Signal(8) # which matcher to apply it to
        self.i_config_we = Signal() # write word to the address

        # connection to the event FIFO
        self.o_event = Signal(31)
        self.o_event_valid = Signal()
        self.i_event_re = Signal() # acknowledge the data

        # version constant output for the get version command
        self.o_gateware_version = Const(GATEWARE_VERSION, 32)

        self.event_fifo = SyncFIFOBuffered(width=31, depth=128)

    def elaborate(self, platform):
        m = Module()

        m.submodules.event_fifo = event_fifo = self.event_fifo

        b = types.SimpleNamespace()
        # synchronize the quite asynchronous SNES bus signals to our domain.
        # this seems to work okay, but the main sd2snes uses more sophisticated
        # techniques to determine the bus state and we may have to steal some.
        for name in dir(self):
            if not name.startswith("i_snes_"): continue
            var = getattr(self, name)
            sync_var = Signal(len(var))
            m.submodules["ffsync_"+name] = FFSynchronizer(var, sync_var)
            setattr(b, name[len("i_snes_"):], sync_var)

        # keep track of the SNES clock cycle so we can time our events. the 29
        # bit counter will overflow every ~25 seconds, but there's something
        # seriously wrong if there aren't any events for a 25 second period. we
        # need the extra 3 bits for event metadata.
        snes_cycle_counter = Signal(29)
        last_clock = Signal()
        m.d.sync += last_clock.eq(b.clock)
        with m.If(~last_clock & b.clock):
            m.d.sync += snes_cycle_counter.eq(snes_cycle_counter + 1)

        # for now we are just concerned with tracing execution. there's no
        # execute signal on the bus, so we just look for the start of a read
        # instead. we assume the address is valid at that point but tbh we're
        # not 100% sure.
        last_rd = Signal()
        snes_read_started = Signal()
        m.d.sync += last_rd.eq(b.rd)
        m.d.comb += snes_read_started.eq(last_rd & ~b.rd)

        # buffer the matcher input signals to ensure the best timing
        mb_addr = Signal(24)
        mb_snes_read_started = Signal()
        mb_config = Signal(32)
        mb_config_addr = Signal(8)
        mb_config_we = Signal()
        m.d.sync += [
            mb_addr.eq(b.addr),
            mb_snes_read_started.eq(snes_read_started),
            mb_config.eq(self.i_config),
            mb_config_addr.eq(self.i_config_addr),
            mb_config_we.eq(self.i_config_we),
        ]

        # wire up all the matchers
        matcher_results = []
        for matcher_num in range(NUM_MATCHERS):
            matcher = Matcher()
            m.submodules["matcher_{}".format(matcher_num)] = matcher
            m.d.comb += [
                matcher.i_snes_addr.eq(mb_addr),
                matcher.i_snes_rd.eq(mb_snes_read_started),

                matcher.i_config.eq(mb_config),
                matcher.i_config_we.eq(mb_config_we & \
                    (mb_config_addr[:MATCHER_BITS] == matcher_num)),
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

        # the final output. will be none if no matchers matched, or the type of
        # that match otherwise.
        matched_type = to_or[0]

        # keep track of when the SNES started waiting for NMI
        wait_cycle = Signal(29)
        currently_waiting = Signal()
        # keep track of which NMI this is. this is just used for ensuring no
        # data is lost.
        nmi_counter = Signal(2)

        # data for an event (the NMI). this data is stored in the event FIFO for
        # the rest of the system
        event_occurred = Signal()
        event_data0 = Signal(30)
        event_data1 = Signal(30)

        with m.Switch(matched_type):
            with m.Case(MATCH_TYPE_RESET):
                m.d.sync += [
                    snes_cycle_counter.eq(0),
                    currently_waiting.eq(0),
                    # first NMI after reset is 0, then 1, 2, 3, 1, 2, 3, etc.
                    nmi_counter.eq(0),
                ]
            with m.Case(MATCH_TYPE_NMI):
                m.d.comb += event_occurred.eq(1)
                m.d.sync += [
                    # first data is the cycle the NMI happened on and the low
                    # bit of the NMI counter
                    event_data0.eq(Cat(
                        snes_cycle_counter,
                        nmi_counter[0],
                    )),
                    # second data is the cycle the SNES started waiting for NMI
                    # and the high bit of the NMI counter
                    event_data1.eq(Cat(
                        # or the current cycle if it never waited
                        Mux(currently_waiting, wait_cycle, snes_cycle_counter),
                        nmi_counter[1],
                    )),
                ]

                m.d.sync += [
                    # don't roll back to 0 so that we can know that 0 is always
                    # the first NMI after reset
                    nmi_counter.eq(Mux(nmi_counter == 3, 1, nmi_counter+1)),
                    currently_waiting.eq(0),
                ]
            with m.Case(MATCH_TYPE_WAIT_START):
                with m.If(~currently_waiting):
                    m.d.sync += [
                        wait_cycle.eq(snes_cycle_counter),
                        currently_waiting.eq(1),
                    ]
            with m.Case(MATCH_TYPE_WAIT_END):
                m.d.sync += currently_waiting.eq(0)

        # write all the pieces of event data to the fifo
        with m.FSM("IDLE"):
            with m.State("IDLE"):
                with m.If(event_occurred):
                    m.next = "DATA0"

            with m.State("DATA0"):
                m.d.comb += [
                    # high bit is 1 for the first word (and 0 for all the rest)
                    event_fifo.w_data.eq(Cat(event_data0, 1)),
                    event_fifo.w_en.eq(1),
                ]
                m.next = "DATA1"

            with m.State("DATA1"):
                m.d.comb += [
                    event_fifo.w_data.eq(Cat(event_data1, 0)),
                    event_fifo.w_en.eq(1),
                ]
                m.next = "IDLE"

        m.d.comb += [
            self.o_event.eq(event_fifo.r_data),
            self.o_event_valid.eq(event_fifo.r_rdy),
            event_fifo.r_en.eq(self.i_event_re),
        ]

        return m
