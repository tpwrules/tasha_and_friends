from nmigen import *
from nmigen.sim.pysim import Simulator, Delay, Settle

from .top import SimTop

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

# basically just used for testing program control
class BasicSimTest:
    def setUp(self):
        self.tb = SimTop()
        self.ev = self.tb.ev

    def simulate(self, name, procs, traces=[]):
        sim = Simulator(self.tb)
        sim.add_clock(1/96e6, domain="sync")

        for proc in procs:
            sim.add_sync_process(proc, domain="sync")

        with sim.write_vcd(name+".vcd", name+".gtkw",
                traces=[ClockDomain("sync").clk, *traces]):
            sim.run_until(10e-6)

    def load_program(self, program):
        for addr, insn in enumerate(program):
            yield self.tb.prg_mem[addr+1].eq(int(insn))

    # run a cycle based test
    def do_cycle_test(self, name, prg, sets, chks, vals, *xprocs):
        # add all the used values as pre-selected traces
        traces = [*sets.values(), *chks.values()]

        to_assert = []
        def proc():
            yield from self.load_program(prg)
            yield
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

if __name__ == "__main__":
    import sys
    import pathlib

    st = SimTop()
    vcd_path = pathlib.Path(sys.argv[1])
    vcd_dir = vcd_path.parent.resolve(strict=True)
    vcd_path = vcd_dir/vcd_path.name
    st.simulate(vcd_path)
