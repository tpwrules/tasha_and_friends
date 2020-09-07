# test basic operation of the Program Control unit to ensure that execution can
# be started and stopped correctly.

from nmigen import *

from .test import SimCoreTest, cycle_test
from ..isa import *

import unittest

class TestProgramControl(SimCoreTest, unittest.TestCase):
    @cycle_test
    def test_start(self):
        prg = [
            POKE(SplW.TMPA, 1),
            POKE(SplW.TMPA, 2),
            POKE(SplW.TMPA, 3),
            POKE(SplW.TMPA, 4),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc,}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            # we start off stopped so the PC should not be incrementing
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
            # when we command a start at PC=1, it will then fetch from PC=1
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 0, "ctl_run": 0}),
            # we should now be running there (even after deasserting start)
            ({"ctl_start": 0},              {"pc": 1, "ctl_run": 1}),
            # keep on going
            ({},                            {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_stop_asserted(self):
        prg = [
            POKE(SplW.TMPA, 1),
            POKE(SplW.TMPA, 2),
            POKE(SplW.TMPA, 3),
            POKE(SplW.TMPA, 4),
            POKE(SplW.TMPA, 5),
            POKE(SplW.TMPA, 6),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc,
                "ctl_stop": self.core.i_ctl_stop}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            # start the program off
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 0, "ctl_run": 0}),
            # we should now be running (even after deasserting start)
            ({"ctl_start": 0},              {"pc": 1, "ctl_run": 1}),
            # execute some instructions
            ({},                            {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
            # oops we're almost at the end! stop!!
            # we should now not be running
            ({"ctl_stop": 1},               {"pc": 4, "ctl_run": 0}),
            # and we shouldn't be fetching either and remain that way even once
            # stop is deasserted
            ({"ctl_stop": 0},               {"pc": 0, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_stop_auto(self):
        prg = [
            POKE(SplW.TMPA, 1),
            POKE(SplW.TMPA, 2),
            POKE(SplW.TMPA, 3),
            POKE(SplW.TMPA, 4),
            BRANCH(0),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            # start the program off
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 1, "ctl_run": 1}),
            # execute some instructions
            ({},                            {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
            # we should now be executing the BRANCH(0)
            ({},                            {"pc": 4, "ctl_run": 1}),
            # which triggers a stop
            ({},                            {"pc": 5, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_start_early(self):
        prg = [
            POKE(SplW.TMPA, 1),
            POKE(SplW.TMPA, 2),
            POKE(SplW.TMPA, 3),
            POKE(SplW.TMPA, 4),
            BRANCH(0),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 1, "ctl_run": 1}),
            ({},                            {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
            # try to restart the program right before it stops
            ({"ctl_start": 1},              {"pc": 4, "ctl_run": 1}),
            # it should be ignored and the program will stop anyway
            ({"ctl_start": 0},              {"pc": 5, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_stop_start(self):
        prg = [
            POKE(SplW.TMPA, 1),
            POKE(SplW.TMPA, 2),
            POKE(SplW.TMPA, 3),
            POKE(SplW.TMPA, 4),
            BRANCH(0),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 1, "ctl_run": 1}),
            ({},                            {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
            ({},                            {"pc": 4, "ctl_run": 1}),
            # try to restart the program the same cycle it stops. it should
            # begin fetching program instructions from the started PC
            ({"ctl_start": 1},              {"pc": 5, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 1, "ctl_run": 1}),
            ({},                            {"pc": 2, "ctl_run": 1}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

if __name__ == "__main__":
    unittest.main()
