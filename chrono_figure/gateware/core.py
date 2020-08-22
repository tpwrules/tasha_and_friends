from nmigen import *
from nmigen.lib.fifo import SyncFIFOBuffered
from nmigen.back import verilog

# all the MATCH_ constants (and NUM_MATCHERS + MATCHER_BITS)
from .match_info import *
from .snes_bus import SNESBus
from .match_engine import MatchEngine, make_match_info

# will probably always be manually incremented because it's related to the
# modules in the sd2snes and its firmware as well
GATEWARE_VERSION = 1002

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
        self.match_engine = MatchEngine()

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = self.bus
        m.submodules.event_fifo = event_fifo = self.event_fifo
        m.submodules.match_engine = match_engine = self.match_engine

        match_info = make_match_info()
        match_valid = Signal()
        m.d.comb += [
            match_engine.i_config.eq(self.i_config),
            match_engine.i_config_addr.eq(self.i_config_addr),
            match_engine.i_config_we.eq(self.i_config_we),

            match_engine.i_bus_valid.eq(bus.o_valid),
            match_engine.i_bus_addr.eq(bus.o_addr),
            match_engine.i_cycle_count.eq(bus.o_cycle_count),

            Cat(*match_info).eq(Cat(*match_engine.o_match_info)),
            match_valid.eq(match_engine.o_match_valid),
        ]

        match_cycle = Signal(29)
        matched_type = Signal(MATCH_TYPE_BITS)
        m.d.comb += [
            match_cycle.eq(match_info.cycle_count),
            matched_type.eq(Mux(match_valid, match_info.match_type, 0)),
        ]

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
        m.d.comb += snes_cycle_counter.eq(match_cycle-counter_offs)

        with m.Switch(matched_type):
            with m.Case(MATCH_TYPE_RESET):
                m.d.sync += [
                    counter_offs.eq(match_cycle),
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
