from nmigen import *

from .isa import *
from .alu import Flags

# handles the PC and starting/stopping the processor
class ProgramControl(Elaboratable):
    def __init__(self):
        # execution control signals
        self.i_ctl_start = Signal() # start execution at the below address
        self.i_ctl_pc = Signal(PC_WIDTH)
        self.o_ctl_run = Signal() # currently running
        self.i_ctl_stop = Signal() # stop execution now

        self.i_branch = Signal() # execute branch this cycle
        self.i_branch_target = Signal(PC_WIDTH)

        self.o_prg_addr = Signal(PC_WIDTH) # what instruction to read next
        self.i_prg_data = Signal(INSN_WIDTH) # the read instruction

        # instruction for read and write cycles. they are the same value, but
        # the right one needs to be used to avoid timing problems
        self.o_cyc_rd_insn = Signal(INSN_WIDTH)
        self.o_cyc_wr_insn = Signal(INSN_WIDTH)
        self.o_fetch_addr = Signal(PC_WIDTH) # insn's address (for debugging)

        self.o_cyc_rd = Signal() # if we are on the read cycle (with a new insn)
        self.o_cyc_wr = Signal() # if we are on the write cycle

    def elaborate(self, platform):
        m = Module()

        # generate alternating read and write signals to drive the core
        which_cyc = Signal()
        cyc_rd = Signal()
        cyc_wr = Signal()
        m.d.sync += which_cyc.eq(~which_cyc)
        m.d.comb += [
            cyc_rd.eq(~which_cyc),
            cyc_wr.eq(which_cyc),

            self.o_cyc_rd.eq(cyc_rd),
            self.o_cyc_wr.eq(cyc_wr),
        ]

        # fetch instructions
        curr_pc = Signal(PC_WIDTH)
        next_pc = Signal(PC_WIDTH)
        curr_insn = Signal(INSN_WIDTH)
        m.d.comb += self.o_cyc_rd_insn.eq(self.i_prg_data)
        m.d.comb += self.o_cyc_wr_insn.eq(curr_insn)
        with m.If(cyc_rd):
            m.d.sync += curr_insn.eq(self.i_prg_data)
            m.d.sync += curr_pc.eq(curr_pc+1)
        with m.Elif(cyc_wr):
            m.d.comb += self.o_prg_addr.eq(next_pc)
            m.d.sync += curr_pc.eq(next_pc)

            # intended for debugging
            m.d.sync += self.o_fetch_addr.eq(self.o_prg_addr)
        
        stopping = Signal()
        stopped = Signal()
        # stop the processor if we branch to address 0
        m.d.comb += stopping.eq(self.i_branch & (self.i_branch_target == 0))
        m.d.comb += self.o_ctl_run.eq(~(stopping | stopped))
        m.d.sync += stopped.eq(stopping | stopped)

        was_start = Signal()
        start_pc = Signal(PC_WIDTH)
        was_stop = Signal()
        m.d.sync += [
            was_start.eq(self.i_ctl_start),
            was_stop.eq(self.i_ctl_stop),
            start_pc.eq(self.i_ctl_pc),
        ]
        do_start = Signal()
        do_stop = Signal()
        m.d.comb += [
            do_start.eq(self.i_ctl_start | was_start),
            do_stop.eq(self.i_ctl_stop | was_stop),
        ]

        # figure out where to fetch them from
        with m.If(cyc_wr):
            # are we being asked to start?
            with m.If(stopping & do_start):
                # yes, set the PC to the new value and start again
                m.d.comb += next_pc.eq(Mux(was_start, start_pc, self.i_ctl_pc))
                m.d.sync += stopped.eq(0)
            with m.Elif(do_stop): # do we want to stop?
                # yes, go to the stop address
                m.d.comb += next_pc.eq(0)
                m.d.sync += stopped.eq(1)
            with m.Elif(self.i_branch): # is the processor trying to branch?
                # yes, set the PC to the target
                m.d.comb += next_pc.eq(self.i_branch_target)
            with m.Else(): # keep on going as before
                m.d.comb += next_pc.eq(curr_pc)

        return m


class EventuatorCore(Elaboratable):
    def __init__(self):
        # execution control signals
        self.i_ctl_start = Signal() # start execution at the below address
        self.i_ctl_pc = Signal(PC_WIDTH)
        self.o_ctl_run = Signal() # currently running
        self.i_ctl_stop = Signal() # stop execution now
        
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

        # special register access signals (dual port)
        self.o_spl_raddr = Signal(REGS_WIDTH)
        self.o_spl_re = Signal()
        self.i_spl_rdata = Signal(DATA_WIDTH)
        self.o_spl_waddr = Signal(REGS_WIDTH)
        self.o_spl_we = Signal()
        self.o_spl_wdata = Signal(DATA_WIDTH)

        # modification signals
        self.o_mod = Signal() # enable modification
        self.o_mod_type = Signal(8)
        self.o_mod_data = Signal(DATA_WIDTH) # data to be modified
        self.i_do_mod = Signal() # if modified data should be stored
        self.i_mod_data = Signal(DATA_WIDTH) # modified data returned

        self.i_flags = Signal(4) # ALU flags to control branches

        self.prg_ctl = ProgramControl()

    def elaborate(self, platform):
        m = Module()

        m.submodules.prg_ctl = prg_ctl = self.prg_ctl

        # hook up program control logic
        cyc_rd = Signal()
        cyc_wr = Signal()
        m.d.comb += [
            prg_ctl.i_ctl_start.eq(self.i_ctl_start),
            prg_ctl.i_ctl_pc.eq(self.i_ctl_pc),
            self.o_ctl_run.eq(prg_ctl.o_ctl_run),
            prg_ctl.i_ctl_stop.eq(self.i_ctl_stop),

            self.o_prg_addr.eq(prg_ctl.o_prg_addr),
            prg_ctl.i_prg_data.eq(self.i_prg_data),

            cyc_rd.eq(prg_ctl.o_cyc_rd),
            cyc_wr.eq(prg_ctl.o_cyc_wr)
        ]

        # instruction we are working on. they are both the same value but the
        # correct one needs to be used to prevent timing problems.
        cyc_rd_insn = Signal(INSN_WIDTH)
        cyc_wr_insn = Signal(INSN_WIDTH)
        m.d.comb += [
            cyc_rd_insn.eq(prg_ctl.o_cyc_rd_insn),
            cyc_wr_insn.eq(prg_ctl.o_cyc_wr_insn),
        ]
        # instruction field selection
        # branch target for BRANCH
        cyc_wr_target = cyc_wr_insn[:PC_WIDTH]
        # branch condition for BRANCH
        cyc_wr_cond = cyc_wr_insn[PC_WIDTH:PC_WIDTH+COND_WIDTH]
        # selection bit; sign for POKE or direction for COPY
        cyc_rd_sel = cyc_rd_insn[15]
        cyc_wr_sel = cyc_wr_insn[15]
        # poke value for POKE
        cyc_wr_val = cyc_wr_insn[:8]
        # register number for COPY and MODIFY
        cyc_rd_reg = cyc_rd_insn[:8]
        cyc_wr_reg = cyc_wr_insn[:8]
        # special register number for COPY and POKE
        cyc_rd_spl = cyc_rd_insn[8:15]
        cyc_wr_spl = cyc_wr_insn[8:15]
        # modification type for MODIFY
        cyc_wr_mod = cyc_wr_insn[8:16]

        # fixed purpose instruction fields
        m.d.comb += [
            prg_ctl.i_branch_target.eq(cyc_wr_target),
            self.o_reg_raddr.eq(cyc_rd_reg),
            self.o_spl_raddr.eq(cyc_rd_spl),
            self.o_spl_waddr.eq(cyc_wr_spl),
            self.o_mod_type.eq(cyc_wr_mod),
        ]

        # store to load forwarding logic
        reg_rdata = Signal(DATA_WIDTH)
        forward = Signal()
        forward_data = Signal(DATA_WIDTH)
        # if we're reading the same register we're writing, we should read the
        # data that we wrote
        m.d.sync += [
            forward.eq((self.o_reg_raddr == self.o_reg_waddr) &
                (self.o_reg_re == 1) & (self.o_reg_we == 1)),
            forward_data.eq(self.o_reg_wdata),
        ]
        m.d.comb += [
            reg_rdata.eq(Mux(forward, forward_data, self.i_reg_rdata)),
            self.o_mod_data.eq(reg_rdata),
        ]

        # process instruction read cycle
        with m.Switch(Cat(cyc_rd_insn[16:], ~cyc_rd)):
            with m.Case(InsnCode.BRANCH):
                pass

            with m.Case(InsnCode.COPY):
                with m.If(cyc_rd_sel): # regular -> special
                    m.d.comb += self.o_reg_re.eq(1)
                with m.Else(): # special -> regular
                    m.d.comb += self.o_spl_re.eq(1)

            with m.Case(InsnCode.POKE):
                pass

            with m.Case(InsnCode.MODIFY):
                m.d.comb += self.o_reg_re.eq(1)

        # handle writing data to registers
        reg_wr_mod = Signal() # write modified data
        reg_wr_spl = Signal() # write read special data
        reg_wr_spl_data = Signal(DATA_WIDTH) # the special data to write
        m.d.sync += [
            self.o_reg_waddr.eq(cyc_wr_reg),
            reg_wr_mod.eq(0),
            reg_wr_spl.eq(0),
            reg_wr_spl_data.eq(self.i_spl_rdata),
        ]
        with m.If(reg_wr_mod):
            m.d.comb += [
                self.o_reg_we.eq(self.i_do_mod),
                self.o_reg_wdata.eq(self.i_mod_data),
            ]
        with m.Elif(reg_wr_spl):
            m.d.comb += [
                self.o_reg_we.eq(1),
                self.o_reg_wdata.eq(reg_wr_spl_data),
            ]

        f = self.i_flags
        branches = {
            Cond.ALWAYS: 1,
            Cond.LEU: ~f[Flags.C] | f[Flags.Z],
            Cond.LTS: f[Flags.S] ^ f[Flags.V],
            Cond.LES: f[Flags.S] ^ f[Flags.V] | f[Flags.Z],
            Cond.Z1: f[Flags.Z],
            Cond.S1: f[Flags.S],
            Cond.C1: f[Flags.C],
            Cond.V1: f[Flags.V],
        }
        should_branch = Signal()
        with m.Switch(cyc_wr_cond[1:]):
            for cond_num, cond in branches.items():
                with m.Case(cond_num >> 1): # low bit inverts branch
                    m.d.comb += should_branch.eq(cond)
        del f, branches

        # process instruction write cycle
        with m.Switch(Cat(cyc_wr_insn[16:], ~cyc_wr)):
            with m.Case(InsnCode.BRANCH):
                m.d.comb += prg_ctl.i_branch.eq(should_branch ^ cyc_wr_cond[0])

            with m.Case(InsnCode.COPY):
                with m.If(cyc_wr_sel): # regular -> special
                    m.d.comb += [
                        self.o_spl_we.eq(1),
                        self.o_spl_wdata.eq(reg_rdata),
                    ]
                with m.Else(): # special -> regular
                    m.d.sync += reg_wr_spl.eq(1)

            with m.Case(InsnCode.POKE):
                m.d.comb += [
                    self.o_spl_we.eq(1),
                    self.o_spl_wdata.eq(Cat(cyc_wr_val, Repl(cyc_wr_sel, 24))),
                ]

            with m.Case(InsnCode.MODIFY):
                m.d.comb += self.o_mod.eq(1)
                m.d.sync += reg_wr_mod.eq(1)

        return m
