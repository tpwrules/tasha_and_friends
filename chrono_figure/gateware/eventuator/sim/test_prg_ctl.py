from nmigen import *
from nmigen.sim.pysim import Delay, Settle

from .test import *
from ..instructions import *

import unittest

class TestProgramControl(BasicSimTest, unittest.TestCase):
    @cycle_test
    def test_start(self):
        prg = [
            POKE(Special.TEST, 1),
            POKE(Special.TEST, 2),
            POKE(Special.TEST, 3),
            POKE(Special.TEST, 4),
        ]
        sets = {"ctl_start": self.ev.i_ctl_start,
                "ctl_pc": self.ev.i_ctl_pc,}
        chks = {"pc": self.ev.o_prg_addr,
                "ctl_run": self.ev.o_ctl_run}
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

        return prg, sets, chks, vals

if __name__ == "__main__":
    unittest.main()
