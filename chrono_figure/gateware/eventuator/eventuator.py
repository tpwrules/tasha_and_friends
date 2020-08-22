from nmigen import *

from ..match_info import *
from .widths import *
from ..match_engine import make_match_info

class Eventuator(Elaboratable):
    def __init__(self):
        # execution control signals
        self.i_ctl_start = Signal() # start execution at the below address
        self.i_ctl_pc = Signal(PC_WIDTH)
        self.o_ctl_run = Signal() # currently running
        self.i_ctl_stop = Signal() # stop execution now
        # jumping to address 0 deasserts run that cycle. if start is asserted,
        # the jump goes to the given PC instead and run is asserted next cycle.
        # asserting stop forces a jump to address 0 that cycle.
        
        # program memory access signals
        # (read is always enabled, even when stopped)
        self.o_prg_addr = Signal(PC_WIDTH)
        self.i_prg_data = Signal(INSN_WIDTH)

        # register memory access signals (dual port)
        self.o_reg_raddr = Signal(REGS_WIDTH)
        self.o_reg_re = Signal()
        self.i_reg_rdata = Signal(DATA_WIDTH)
        self.o_reg_waddr = Signal(REGS_WIDTH)
        self.o_reg_we = Signal()
        self.o_reg_wdata = Signal(DATA_WIDTH)

        # match info input signals
        self.i_match_info = make_match_info()
        self.i_match_valid = Signal()
        self.o_match_re = Signal()

        # match config access signals
        self.o_match_config = Signal(32)
        self.o_match_config_addr = Signal(8)
        self.o_match_config_we = Signal()

        # event data fifo signals
        self.o_event = Signal(31)
        self.o_event_valid = Signal()
        self.i_event_space = Signal() # space for more valid events

    def elaborate(self, platform):
        m = Module()

        match_cycle = Signal(29)
        matched_type = Signal(MATCH_TYPE_BITS)
        m.d.comb += [
            match_cycle.eq(self.i_match_info.cycle_count),
            matched_type.eq(
                Mux(self.i_match_valid, self.i_match_info.match_type, 0)),
            self.o_match_re.eq(self.i_match_valid),
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
                    self.o_event.eq(Cat(event_data0, 1)),
                    self.o_event_valid.eq(1),
                ]
                m.next = "DATA1"

            with m.State("DATA1"):
                m.d.comb += [
                    self.o_event.eq(Cat(event_data1, 0)),
                    self.o_event_valid.eq(1),
                ]
                m.next = "IDLE"

        return m
