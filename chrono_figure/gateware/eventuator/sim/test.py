from nmigen import *
from nmigen.sim.pysim import Simulator, Delay, Settle

from .top import SimTop, SimCoreTop

import functools

def cycle_test(case):
    @functools.wraps(case)
    def wrapper(self):
        try:
            self.do_cycle_test(case.__name__, *case(self))
        except AssertionError as error:
            error.__traceback__ = None
            raise error
    return wrapper

class BaseSimTest:
    def simulate(self, name, procs, traces=[]):
        sim = Simulator(self.tb)
        sim.add_clock(1/96e6, domain="sync")

        for proc in procs:
            sim.add_sync_process(proc, domain="sync")

        with sim.write_vcd(name+".vcd", name+".gtkw",
                traces=[self.tb.o_clk, *traces]):
            sim.run_until(10e-6)

    # run a cycle based test
    def do_cycle_test(self, name, sets, chks, vals, *xprocs):
        # add all the used values as pre-selected traces
        traces = [*sets.values(), *chks.values()]

        to_assert = []
        def proc():
            cycle = 1 # cycle 0 is used to load the program
            for set_vals, chk_vals in vals:
                for n, v in set_vals.items(): # set the set values
                    yield sets[n].eq(v)
                yield Settle() # wait for everything to propagate
                for n, v in chk_vals.items(): # check the check values
                    # save them for later so we can complete the simulation
                    # without throwing an error
                    to_assert.append(((yield chks[n]), v, 
                        "chk {} on cycle {}".format(n, cycle)))
                yield # wait for next cycle and do it again
                cycle += 1

        self.simulate(name, [proc, *xprocs], traces)
        # make sure everything went okay
        for got, expected, msg in to_assert:
            self.assertEqual(got, expected, msg)

class SimCoreTest(BaseSimTest):
    def setUp(self):
        self.tb = SimCoreTop(prg_d=32, reg_d=32)
        self.core = self.tb.core

    # simulation process to load the given program into program memory
    def proc_load_prg(self, prg):
        def proc():
            for addr, insn in enumerate(prg):
                yield self.tb.prg_mem[addr+1].eq(int(insn))
        return proc

    # simulation process to load the given program and start it
    def proc_start_prg(self, prg):
        def proc():
            yield from self.proc_load_prg(prg)()
            yield self.core.i_ctl_start.eq(1)
            yield self.core.i_ctl_pc.eq(1)
            yield
            yield self.core.i_ctl_start.eq(0)
        return proc

class SimTest(BaseSimTest):
    def setUp(self):
        self.tb = SimTop(match_d=4, event_d=4, prg_d=32, reg_d=32)
        self.ev = self.tb.ev
        self.core = self.tb.ev.core

    # simulation process to load the given program into program memory
    def proc_load_prg(self, prg):
        def proc():
            for addr, insn in enumerate(prg):
                yield self.tb.prg_mem[addr+1].eq(int(insn))
        return proc

    # simulation process to load the given program and start it
    def proc_start_prg(self, prg):
        def proc():
            yield from self.proc_load_prg(prg)()
            yield self.ev.i_ctl_start.eq(1)
            yield self.ev.i_ctl_pc.eq(1)
            yield
            yield self.ev.i_ctl_start.eq(0)
        return proc

if __name__ == "__main__":
    import unittest
    # import and run all the tests
    from .test_prg_ctl import TestProgramControl
    from .test_core import TestCore
    from .test_exec import TestExecution

    unittest.main()
