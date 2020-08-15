from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.back import verilog

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .snes_bus import SNESBus

# will probably always be manually incremented because it's related to the
# modules in the sd2snes and its firmware as well
GATEWARE_VERSION = 1001

class Matcher(Elaboratable):
    def __init__(self):
        self.i_snes_addr = Signal(24) # address the snes is accessing
        self.i_snes_rd = Signal() # 1 the cycle the snes starts reading

        # configuration input to set type and address
        self.i_config_data = Signal(8)
        self.i_config_we = Signal(4) # one per byte

        self.o_match_type = Signal(MATCH_TYPE_BITS)

    def elaborate(self, platform):
        m = Module()

        match_addr = Signal(24)
        match_type = Signal(MATCH_TYPE_BITS)

        with m.If(self.i_config_we[0]):
            m.d.sync += match_addr[0:8].eq(self.i_config_data)
        with m.If(self.i_config_we[1]):
            m.d.sync += match_addr[8:16].eq(self.i_config_data)
        with m.If(self.i_config_we[2]):
            m.d.sync += match_addr[16:24].eq(self.i_config_data)
        with m.If(self.i_config_we[3]):
            m.d.sync += match_type.eq(self.i_config_data[0:MATCH_TYPE_BITS])

        with m.If(self.i_snes_rd):
            with m.If(self.i_snes_addr == match_addr):
                m.d.comb += self.o_match_type.eq(match_type)

        return m


class ChronoFigureCore(Elaboratable):
    def __init__(self, cart_signals):
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
        self.bus = SNESBus(cart_signals)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = self.bus
        m.submodules.event_fifo = event_fifo = self.event_fifo

        # buffer the matcher input signals to ensure the best timing
        mb_addr = Signal(24)
        mb_valid = Signal()
        m.d.sync += [
            mb_addr.eq(bus.o_addr),
            mb_valid.eq(bus.o_valid),
        ]

        mb_config_data = Signal(8)
        mb_config_addr = Signal(MATCHER_BITS)
        mb_config_we = Signal(4) # one line per byte
        # convert 32 bit config word into four 8 bit writes
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

        # the final output. will be none if no matchers matched, or the type of
        # that match otherwise.
        matched_type = to_or[0]

        # keep track of when the SNES started waiting for NMI
        wait_cycle = Signal(29)
        currently_waiting = Signal()
        # keep track of which event this is. this is just used for ensuring no
        # data is lost.
        event_counter = Signal(2)

        # data for an event (the NMI). this data is stored in the event FIFO for
        # the rest of the system
        event_occurred = Signal()
        event_data0 = Signal(30)
        event_data1 = Signal(30)

        snes_cycle_counter = Signal(29)
        counter_offs = Signal(29)
        m.d.comb += snes_cycle_counter.eq(bus.o_cycle_count[:29]-counter_offs)

        with m.Switch(matched_type):
            with m.Case(MATCH_TYPE_RESET):
                m.d.sync += [
                    counter_offs.eq(bus.o_cycle_count[:29]),
                    currently_waiting.eq(0),
                    # first event after reset is 0, then 1, 2, 3, 1, 2, 3, etc.
                    event_counter.eq(0),
                ]
            with m.Case(MATCH_TYPE_NMI):
                m.d.comb += event_occurred.eq(1)
                m.d.sync += [
                    # first data is the cycle the NMI happened on and the low
                    # bit of the event counter
                    event_data0.eq(Cat(
                        snes_cycle_counter,
                        event_counter[0],
                    )),
                    # second data is the cycle the SNES started waiting for NMI
                    # and the high bit of the event counter
                    event_data1.eq(Cat(
                        # or the current cycle if it never waited
                        Mux(currently_waiting, wait_cycle, snes_cycle_counter),
                        event_counter[1],
                    )),
                ]

                m.d.sync += [
                    # don't roll back to 0 so that we can know that 0 is always
                    # the first event after reset
                    event_counter.eq(Mux(event_counter==3, 1, event_counter+1)),
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
