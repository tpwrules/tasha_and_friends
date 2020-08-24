from nmigen import *

from .widths import *
from .instructions import *

# handles the PC and starting/stopping the processor
class ProgramControl(Elaboratable):
    def __init__(self):
        # execution control signals
        self.i_ctl_start = Signal() # start execution at the below address
        self.i_ctl_pc = Signal(PC_WIDTH)
        self.o_ctl_run = Signal() # currently running
        self.i_ctl_stop = Signal() # stop execution now
        # branching to address 0 deasserts run that cycle. if start is asserted,
        # the branch goes to the given PC instead and run is asserted next cycle.
        # asserting stop forces a branch to address 0 that cycle.

        self.i_branch = Signal() # execute branch this cycle
        self.i_branch_target = Signal(PC_WIDTH)

        self.o_prg_addr = Signal(PC_WIDTH) # what instruction to read next
        self.o_branch_0 = Signal() # force a branch to PC=0 (i.e. stop)

    def elaborate(self, platform):
        m = Module()

        # this is all disgusting combinatorial logic. hopefully it's fast!

        stopping = Signal()
        # stop the processor if we branch to address 0
        m.d.comb += stopping.eq(self.i_branch & (self.i_branch_target == 0))
        # if a stop is requested, we force the processor to branch to address 0
        # and so trigger a stop itself
        m.d.comb += self.o_branch_0.eq(self.i_ctl_stop)

        curr_pc = Signal(PC_WIDTH)
        stopped = Signal()
        m.d.sync += stopped.eq(stopping)
        m.d.comb += self.o_ctl_run.eq(~(stopping | stopped))

        # are we being asked to start?
        with m.If(stopping & self.i_ctl_start):
            # yes, set the PC to the new value and start again
            m.d.comb += self.o_prg_addr.eq(self.i_ctl_pc)
            m.d.sync += [
                stopped.eq(0),
                curr_pc.eq(self.i_ctl_pc+1),
            ]
        with m.Elif(self.i_branch): # is the processor trying to branch?
            # yes, set the PC to the target
            m.d.comb += self.o_prg_addr.eq(self.i_branch_target)
            m.d.sync += curr_pc.eq(self.i_branch_target+1)
        with m.Else():
            # increment the PC like normal
            m.d.comb += self.o_prg_addr.eq(curr_pc)
            m.d.sync += curr_pc.eq(curr_pc+1)

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
        self.i_mod_data = Signal(DATA_WIDTH) # modified data returned

        self.prg_ctl = ProgramControl()

    def elaborate(self, platform):
        m = Module()

        m.submodules.prg_ctl = prg_ctl = self.prg_ctl

        # hook up program control logic
        force_branch_0 = Signal()
        m.d.comb += [
            prg_ctl.i_ctl_start.eq(self.i_ctl_start),
            prg_ctl.i_ctl_pc.eq(self.i_ctl_pc),
            self.o_ctl_run.eq(prg_ctl.o_ctl_run),
            prg_ctl.i_ctl_stop.eq(self.i_ctl_stop),

            self.o_prg_addr.eq(prg_ctl.o_prg_addr),
            force_branch_0.eq(prg_ctl.o_branch_0),
        ]

        # instruction being fetched (and slightly executed)
        fetch_insn = Signal(INSN_WIDTH)
        # instruction being executed and completed
        exec_insn = Signal(INSN_WIDTH)
        m.d.sync += exec_insn.eq(fetch_insn)
        m.d.comb += fetch_insn.eq(Mux(force_branch_0, 0, self.i_prg_data))

        # instruction field selection
        # branch target for BRANCH
        fetch_target = fetch_insn[:PC_WIDTH]
        # branch condition for BRANCH
        fetch_cond = fetch_insn[PC_WIDTH:PC_WIDTH+COND_WIDTH]
        # selection bit; sign for POKE or direction for COPY
        fetch_sel = fetch_insn[15]
        exec_sel = exec_insn[15]
        # poke value for POKE
        exec_val = exec_insn[:8]
        # register number for COPY and MODIFY
        fetch_reg = fetch_insn[:8]
        exec_reg = exec_insn[:8]
        # special register number for COPY and POKE
        fetch_spl = fetch_insn[8:15]
        exec_spl = exec_insn[8:15]
        # modification type for MODIFY
        exec_mod = exec_insn[8:16]

        # fixed purpose instruction fields
        m.d.comb += [
            prg_ctl.i_branch_target.eq(fetch_target),
            self.o_reg_raddr.eq(fetch_reg),
            self.o_reg_waddr.eq(exec_reg),
            self.o_spl_raddr.eq(fetch_spl),
            self.o_spl_waddr.eq(exec_spl),
            self.o_mod_type.eq(exec_mod),
            self.o_mod_data.eq(self.i_reg_rdata),
        ]

        # decoding of fetched instruction. this just sets up the reads of memory
        # (and also executes branch instructions so we don't have delay slots)
        with m.Switch(fetch_insn[16:]):
            with m.Case(InsnCode.BRANCH):
                should_branch = Signal()
                with m.Switch(fetch_cond):
                    with m.Case(Cond.ALWAYS):
                        m.d.comb += should_branch.eq(1)
                    with m.Case(Cond.NEVER):
                        m.d.comb += should_branch.eq(0)

                m.d.comb += prg_ctl.i_branch.eq(should_branch)

            with m.Case(InsnCode.COPY):
                with m.If(fetch_sel): # regular -> special
                    m.d.comb += self.o_reg_re.eq(1)
                with m.Else(): # special -> regular
                    m.d.comb += self.o_spl_re.eq(1),

            with m.Case(InsnCode.POKE):
                pass # all the action is on the execute cycle

            with m.Case(InsnCode.MODIFY):
                m.d.comb += self.o_reg_re.eq(1)

        # execution of instruction. does the thing with the read memory value
        with m.Switch(exec_insn[16:]):
            with m.Case(InsnCode.BRANCH):
                pass # all the action is on the fetch cycle

            with m.Case(InsnCode.COPY):
                with m.If(exec_sel): # regular -> special
                    m.d.comb += [
                        self.o_spl_we.eq(1),
                        self.o_spl_wdata.eq(self.i_reg_rdata),
                    ]
                with m.Else(): # special -> regular
                    m.d.comb += [
                        self.o_reg_we.eq(1),
                        self.o_reg_wdata.eq(self.i_spl_rdata),
                    ]

            with m.Case(InsnCode.POKE):
                m.d.comb += [
                    self.o_spl_we.eq(1),
                    self.o_spl_wdata.eq(Cat(exec_val, Repl(exec_sel, 24))),
                ]

            with m.Case(InsnCode.MODIFY):
                m.d.comb += [
                    self.o_mod.eq(1),
                    self.o_reg_we.eq(1),
                    self.o_reg_wdata.eq(self.i_mod_data),
                ]

        return m
