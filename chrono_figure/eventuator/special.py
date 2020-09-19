from nmigen import *

from chrono_figure.gateware.match_engine import make_match_info
from .isa import *

# stores two temporary values called TMPA and TMPB which can be arbitrarily read
# and written
class TemporaryUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(1)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(1)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

    def elaborate(self, platform):
        m = Module()

        tmp_a = Signal(DATA_WIDTH)
        tmp_b = Signal(DATA_WIDTH)

        with m.If(self.i_we):
            with m.If(self.i_waddr == SplW.TMPA_OFFSET):
                m.d.sync += tmp_a.eq(self.i_wdata)
            with m.Elif(self.i_waddr == SplW.TMPB_OFFSET):
                m.d.sync += tmp_b.eq(self.i_wdata)

        did_re = Signal()
        last_raddr = Signal(1)
        m.d.sync += [
            did_re.eq(self.i_re),
            last_raddr.eq(self.i_raddr),
        ]
        with m.If(did_re):
            with m.If(last_raddr == SplR.TMPA_OFFSET):
                m.d.comb += self.o_rdata.eq(tmp_a)
            with m.Elif(last_raddr == SplR.TMPB_OFFSET):
                m.d.comb += self.o_rdata.eq(tmp_b)

        return m


# assists in generating full 32 bit immediates. writing to the Bn register
# stores the low 8 bits of the value to byte n and sign extends the 9th bit to
# all bytes above n. it does not touch bytes below n.
class ImmediateUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(2)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(2)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

    def elaborate(self, platform):
        m = Module()

        immediate = Signal(DATA_WIDTH)

        ext_data = Cat(self.i_wdata[:8], Repl(self.i_wdata[8], 24))
        with m.If(self.i_we):
            with m.Switch(self.i_waddr):
                for byte in range(4):
                    with m.Case(getattr(SplW, "IMM_B{}_OFFSET".format(byte))):
                        m.d.sync += immediate.eq(
                            Cat(immediate[:byte*8], ext_data))

        # there is only one thing to read so we don't bother listening to the
        # bus signals. assigning it combinatorially means store to load
        # forwarding is not necessary
        m.d.comb += self.o_rdata.eq(immediate)

        return m

# writes words to the event FIFO
class EventFIFOUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(0)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(0)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

        self.o_event = Signal(32)
        self.o_event_we = Signal()
        self.i_event_space = Signal()
        self.o_ctl_pause = Signal()

    def elaborate(self, platform):
        m = Module()

        m.d.sync += [
            self.o_event.eq(self.i_wdata),
            self.o_event_we.eq(self.i_we & self.i_event_space),
        ]
        # tell the processor to stop advancing the PC (and thus retry the
        # instruction) if we don't have space to store the data
        m.d.comb += self.o_ctl_pause.eq(self.i_we & ~self.i_event_space)

        return m

# configures the matchers (including auto-increment function!)
class MatcherConfigUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(1)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(1)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

        self.o_match_config = Signal(8)
        self.o_match_config_addr = Signal(10)
        self.o_match_config_we = Signal()

    def elaborate(self, platform):
        m = Module()

        curr_addr = Signal(10)
        m.d.sync += self.o_match_config_we.eq(0)
        with m.If(self.i_we):
            with m.If(self.i_waddr == SplW.MATCH_CONFIG_ADDR_OFFSET):
                m.d.sync += curr_addr.eq(self.i_wdata)
            with m.Elif(self.i_waddr == SplW.MATCH_CONFIG_DATA_OFFSET):
                m.d.sync += self.o_match_config_we.eq(1)
                m.d.sync += curr_addr.eq(curr_addr + 1)

        m.d.sync += [
            self.o_match_config.eq(self.i_wdata),
            self.o_match_config_addr.eq(curr_addr),
        ]

        return m

# read out the info of the current match
class MatchInfoUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(2)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(2)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

        self.i_match_info = make_match_info()
        self.o_match_enable = Signal()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i_we):
            # only one thing to write, so ignore the address
            m.d.comb += self.o_match_enable.eq(1)

        with m.Switch(self.i_waddr):
            with m.Case(SplR.MATCH_TYPE_OFFSET):
                m.d.comb += self.o_rdata.eq(self.i_match_info.match_type)
            with m.Case(SplR.MATCH_CYCLE_COUNT_OFFSET):
                m.d.comb += self.o_rdata.eq(self.i_match_info.cycle_count)
            with m.Case(SplR.MATCH_ADDR_OFFSET):
                m.d.comb += self.o_rdata.eq(self.i_match_info.addr)
            with m.Case(SplR.MATCH_DATA_OFFSET):
                m.d.comb += self.o_rdata.eq(self.i_match_info.data)

        return m

class ModOffsetUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(2)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(2)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

        self.i_mod = Signal()
        self.i_ctl_start = Signal()
        self.o_mod_offset_rd = Signal(REGS_WIDTH)
        self.o_mod_offset_wr = Signal(REGS_WIDTH)

    def elaborate(self, platform):
        m = Module()

        hold = Signal()
        with m.If((~hold & self.i_mod) | self.i_ctl_start):
            m.d.sync += [
                hold.eq(~self.i_ctl_start),
                self.o_mod_offset_rd.eq(0),
                self.o_mod_offset_wr.eq(0),
            ]

        with m.If(self.i_we):
            with m.If(self.i_waddr[0] == SplW.MOFF_RD_TEMP_OFFSET):
                m.d.sync += self.o_mod_offset_rd.eq(self.i_wdata)
            with m.Elif(self.i_waddr[0] == SplW.MOFF_WR_TEMP_OFFSET):
                m.d.sync += self.o_mod_offset_wr.eq(self.i_wdata)
            m.d.sync += hold.eq(self.i_waddr[1])

        return m

class BranchIndirectUnit(Elaboratable):
    def __init__(self):
        # special bus signals
        self.i_raddr = Signal(0)
        self.i_re = Signal()
        self.o_rdata = Signal(DATA_WIDTH)
        self.i_waddr = Signal(0)
        self.i_we = Signal()
        self.i_wdata = Signal(DATA_WIDTH)

        self.o_branch_ind = Signal()
        self.o_branch_ind_target = Signal(PC_WIDTH)
        self.i_branch_exec = Signal()
        self.i_prg_addr = Signal(PC_WIDTH)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i_we):
            m.d.sync += [
                self.o_branch_ind_target.eq(self.i_wdata),
                self.o_branch_ind.eq(1),
            ]
        with m.Elif(self.i_branch_exec):
            m.d.sync += self.o_branch_ind.eq(0)

        pc_temp = Signal(PC_WIDTH)
        m.d.sync += [
            pc_temp.eq(self.i_prg_addr),
            self.o_rdata.eq(pc_temp),
        ]

        return m
