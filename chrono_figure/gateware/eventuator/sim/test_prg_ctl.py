# test basic operation of the Program Control unit to ensure that execution can
# be started and stopped correctly.

from nmigen import *

from .test import SimCoreTest, cycle_test
from ..instructions import *

import unittest

class TestProgramControl(SimCoreTest, unittest.TestCase):
    @cycle_test
    def test_start(self):
        prg = [
            POKE(Special.TEST, 1),
            POKE(Special.TEST, 2),
            POKE(Special.TEST, 3),
            POKE(Special.TEST, 4),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc,}
        chks = {"pc": self.core.o_prg_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            # we start off stopped so the PC should not be incrementing
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
            # when we command a start at PC=1, it will then fetch from PC=1
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 1, "ctl_run": 0}),
            # we should now be running (even after deasserting start)
            ({"ctl_start": 0},              {"pc": 2, "ctl_run": 1}),
            # keep on going
            ({},                            {"pc": 3, "ctl_run": 1}),
            ({},                            {"pc": 4, "ctl_run": 1}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_stop_asserted(self):
        prg = [
            POKE(Special.TEST, 1),
            POKE(Special.TEST, 2),
            POKE(Special.TEST, 3),
            POKE(Special.TEST, 4),
            POKE(Special.TEST, 5),
            POKE(Special.TEST, 6),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc,
                "ctl_stop": self.core.i_ctl_stop}
        chks = {"pc": self.core.o_prg_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            # start the program off
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 1, "ctl_run": 0}),
            # we should now be running (even after deasserting start)
            ({"ctl_start": 0},              {"pc": 2, "ctl_run": 1}),
            # execute some instructions
            ({},                            {"pc": 3, "ctl_run": 1}),
            ({},                            {"pc": 4, "ctl_run": 1}),
            # oops we're almost at the end! stop!!
            # we should now not be running and fetch from PC=0
            ({"ctl_stop": 1},               {"pc": 0, "ctl_run": 0}),
            # and we should remain that way even once stop is deasserted
            ({"ctl_stop": 0},               {"pc": 0, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_stop_auto(self):
        prg = [
            POKE(Special.TEST, 1),
            POKE(Special.TEST, 2),
            POKE(Special.TEST, 3),
            POKE(Special.TEST, 4),
            BRANCH(0),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc}
        chks = {"pc": self.core.o_prg_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            # start the program off
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 1, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 2, "ctl_run": 1}),
            # execute some instructions
            ({},                            {"pc": 3, "ctl_run": 1}),
            ({},                            {"pc": 4, "ctl_run": 1}),
            # we should now be executing the BRANCH(0)
            ({},                            {"pc": 5, "ctl_run": 1}),
            # which triggers a stop
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_start_early(self):
        prg = [
            POKE(Special.TEST, 1),
            POKE(Special.TEST, 2),
            POKE(Special.TEST, 3),
            POKE(Special.TEST, 4),
            BRANCH(0),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc}
        chks = {"pc": self.core.o_prg_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 1, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
            ({},                            {"pc": 4, "ctl_run": 1}),
            # try to restart the program right before it stops
            ({"ctl_start": 1},              {"pc": 5, "ctl_run": 1}),
            # it should be ignored and the program will stop anyway
            ({"ctl_start": 0},              {"pc": 0, "ctl_run": 0}),
            ({},                            {"pc": 0, "ctl_run": 0}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

    @cycle_test
    def test_stop_start(self):
        prg = [
            POKE(Special.TEST, 1),
            POKE(Special.TEST, 2),
            POKE(Special.TEST, 3),
            POKE(Special.TEST, 4),
            BRANCH(0),
        ]
        sets = {"ctl_start": self.core.i_ctl_start,
                "ctl_pc": self.core.i_ctl_pc}
        chks = {"pc": self.core.o_prg_addr,
                "ctl_run": self.core.o_ctl_run}
        vals = [
            ({},                            {"pc": 0, "ctl_run": 0}),
            ({"ctl_start": 1, "ctl_pc": 1}, {"pc": 1, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
            ({},                            {"pc": 4, "ctl_run": 1}),
            ({},                            {"pc": 5, "ctl_run": 1}),
            # try to restart the program the same cycle it stops. it should
            # immediately begin fetching program instructions
            ({"ctl_start": 1},              {"pc": 1, "ctl_run": 0}),
            ({"ctl_start": 0},              {"pc": 2, "ctl_run": 1}),
            ({},                            {"pc": 3, "ctl_run": 1}),
        ]

        return sets, chks, vals, self.proc_load_prg(prg)

if __name__ == "__main__":
    unittest.main()
