# test basic execution of the instructions to ensure their data processing is
# correct and that the regular registers, special registers, and modification
# all work at a basic level

from nmigen import *

from .test import SimTest, cycle_test
from ..instructions import *

import unittest

class TestExecution(SimTest, unittest.TestCase):
    @cycle_test
    def test_COPY_from_spl_exec(self):
        prg = [
            POKE(SplW.TMPA, 1), # poke some values into the temp special regs
            POKE(SplW.TMPB, 2),
            COPY(3, SplR.TMPA), # read them back and check the values
            COPY(4, SplR.TMPB),
            POKE(SplW.TMPA, 5), # write different values and make sure the
            POKE(SplW.TMPB, 6), #  registers do not change
            COPY(3, SplR.TMPA), # read those back and make sure they change now
            COPY(4, SplR.TMPB),
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3], "r4": self.tb.reg_mem[4]}
        vals = [
            *[({}, {})]*5,
            ({}, {"r3": 1}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 5, "r4": 2}),
            ({}, {"r3": 5, "r4": 6}),
            ({}, {"r3": 5, "r4": 6}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_COPY_to_spl_exec(self):
        prg = [
            POKE(SplW.TMPA, 1), # get some values into the regular registers
            POKE(SplW.TMPB, 2), #  by reading them from the specials, which we
            COPY(3, SplR.TMPA), #  already checked works
            COPY(4, SplR.TMPB),
            POKE(SplW.TMPA, 5), # change the values in the special registers to
            POKE(SplW.TMPB, 6), #  a result we don't want
            COPY(SplW.TMPA, 3), # write the values we do want
            COPY(SplW.TMPB, 4),
            COPY(5, SplR.TMPA), # and read them back to make sure we got it
            COPY(6, SplR.TMPB),
        ]
        sets = {}
        chks = {"r5": self.tb.reg_mem[5], "r6": self.tb.reg_mem[6]}
        vals = [
            *[({}, {})]*11,
            ({}, {"r5": 1}),
            ({}, {"r5": 1, "r6": 2}),
            ({}, {"r5": 1, "r6": 2}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_MODIFY_exec(self):
        prg = [
            POKE(SplW.TMPA, 1), # get some values into the regular registers
            POKE(SplW.TMPB, 2), #  by reading them from the specials, which we
            COPY(3, SplR.TMPA), #  already checked works
            COPY(4, SplR.TMPB),
            MODIFY(Mod.COPY, 3), # copy the registers to themselves and verify
            MODIFY(Mod.COPY, 4), #  that the values do not change
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3], "r4": self.tb.reg_mem[4]}
        vals = [
            *[({}, {})]*5,
            ({}, {"r3": 1}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 1, "r4": 2}),
            ({}, {"r3": 1, "r4": 2}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_reg_store_to_load(self):
        prg = [
            POKE(SplW.TMPA, 1), # get some values into the regular registers
            POKE(SplW.TMPB, 2), #  by reading them from the specials, which we
            COPY(3, SplR.TMPA), #  already checked works
            COPY(3, SplR.TMPB),
            COPY(SplW.TMPA, 3), # read the register we just wrote
            POKE(SplW.TMPB, 6),
            COPY(4, SplR.TMPA), # did we get that back?
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3], "r4": self.tb.reg_mem[4]}
        vals = [
            *[({}, {})]*5,
            ({}, {"r3": 1}),
            ({}, {"r3": 2}),
            ({}, {"r3": 2}),
            ({}, {"r3": 2}),
            ({}, {"r3": 2, "r4": 2}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
