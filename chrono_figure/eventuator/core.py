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

        self.o_fetch_insn = Signal(INSN_WIDTH) # insn that was just fetched
        self.o_fetch_addr = Signal(PC_WIDTH) # its address (for debugging)
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
        with m.If(cyc_rd):
            m.d.comb += self.o_fetch_insn.eq(self.i_prg_data)
            m.d.sync += curr_insn.eq(self.i_prg_data)
            m.d.sync += curr_pc.eq(curr_pc+1)
        with m.Elif(cyc_wr):
            m.d.comb += self.o_fetch_insn.eq(curr_insn)
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
        # branching to address 0 deasserts run that cycle. if start is asserted,
        # the branch goes to the given PC instead and run is asserted next
        # cycle. asserting stop forces a branch to address 0 that cycle.
        
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

        # instruction we are working on
        curr_insn = Signal(INSN_WIDTH)
        m.d.comb += curr_insn.eq(prg_ctl.o_fetch_insn)
        # instruction field selection
        # branch target for BRANCH
        insn_target = curr_insn[:PC_WIDTH]
        # branch condition for BRANCH
        insn_cond = curr_insn[PC_WIDTH:PC_WIDTH+COND_WIDTH]
        # selection bit; sign for POKE or direction for COPY
        insn_sel = curr_insn[15]
        # poke value for POKE
        insn_val = curr_insn[:8]
        # register number for COPY and MODIFY
        insn_reg = curr_insn[:8]
        # special register number for COPY and POKE
        insn_spl = curr_insn[8:15]
        # modification type for MODIFY
        insn_mod = curr_insn[8:16]

        # fixed purpose instruction fields
        m.d.comb += [
            prg_ctl.i_branch_target.eq(insn_target),
            self.o_reg_raddr.eq(insn_reg),
            self.o_spl_raddr.eq(insn_spl),
            self.o_spl_waddr.eq(insn_spl),
            self.o_mod_type.eq(insn_mod),
        ]

        m.d.sync += [
            self.o_reg_waddr.eq(insn_reg),
            self.o_reg_we.eq(0),
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

        # decode and execute the instruction
        with m.Switch(Cat(curr_insn[16:], cyc_rd)):
            with m.Case(InsnCode.BRANCH+4): # read cycle
                pass

            with m.Case(InsnCode.BRANCH+0): # write cycle
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
                with m.Switch(insn_cond[1:]):
                    for cond_num, cond in branches.items():
                        with m.Case(cond_num >> 1): # low bit inverts branch
                            m.d.comb += should_branch.eq(cond)
                del f, branches

                m.d.comb += prg_ctl.i_branch.eq(should_branch ^ insn_cond[0])

            with m.Case(InsnCode.COPY+4): # read cycle
                with m.If(insn_sel): # regular -> special
                    m.d.comb += self.o_reg_re.eq(1)
                with m.Else(): # special -> regular
                    m.d.comb += self.o_spl_re.eq(1)

            with m.Case(InsnCode.COPY+0): # write cycle
                with m.If(insn_sel): # regular -> special
                    m.d.comb += [
                        self.o_spl_we.eq(1),
                        self.o_spl_wdata.eq(reg_rdata),
                    ]
                with m.Else(): # special -> regular
                    m.d.sync += [
                        self.o_reg_we.eq(1),
                        self.o_reg_wdata.eq(self.i_spl_rdata),
                    ]

            with m.Case(InsnCode.POKE+4): # read cycle
                pass

            with m.Case(InsnCode.POKE+0): # write cycle
                m.d.comb += [
                    self.o_spl_we.eq(1),
                    self.o_spl_wdata.eq(Cat(insn_val, Repl(insn_sel, 24))),
                ]

            with m.Case(InsnCode.MODIFY+4): # read cycle
                m.d.comb += self.o_reg_re.eq(1)

            with m.Case(InsnCode.MODIFY+0): # write cycle
                m.d.comb += self.o_mod.eq(1)
                m.d.sync += [
                    self.o_reg_we.eq(self.i_do_mod),
                    self.o_reg_wdata.eq(self.i_mod_data),
                ]

        return m
