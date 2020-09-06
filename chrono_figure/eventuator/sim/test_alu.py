# test the ALU functions

from nmigen import *

from .test import SimTest, cycle_test
from ..isa import *

import unittest

class TestALU(SimTest, unittest.TestCase):
    @cycle_test
    def test_ALU_inputs(self):
        prg = [
            POKE(SplW.TMPA, 69),
            POKE(SplW.ALU_B0, 2),
            POKE(SplW.ALU_B1, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.ADD_0, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.INC, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.ADD_B0, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.ADD_B1, 3),
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3]}
        vals = [
            *[({}, {})]*6,
            ({}, {}), ({}, {"r3": 69}),
            ({}, {}), ({}, {"r3": 70}),
            ({}, {}), ({}, {"r3": 71}),
            ({}, {}), ({}, {"r3": 72}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_ALU_operations(self):
        prg = [
            POKE(SplW.TMPA, 69),
            POKE(SplW.ALU_B0, 43),
            COPY(3, SplR.TMPA), MODIFY(Mod.AND_B0, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.OR_B0, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.XOR_B0, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.ADD_B0, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.SUB_B0, 3),

            COPY(3, SplR.TMPA), MODIFY(Mod.SHIFT_LEFT, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.SHIFT_RIGHT, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.ROTATE_LEFT, 3),
            COPY(3, SplR.TMPA), MODIFY(Mod.ROTATE_RIGHT, 3),
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3]}
        vals = [
            *[({}, {})]*5,
            ({}, {}), ({}, {"r3": 69 & 43}),
            ({}, {}), ({}, {"r3": 69 | 43}),
            ({}, {}), ({}, {"r3": 69 ^ 43}),
            ({}, {}), ({}, {"r3": 69 + 43}),
            ({}, {}), ({}, {"r3": 69 - 43}),

            ({}, {}), ({}, {"r3": 69 << 1}),
            ({}, {}), ({}, {"r3": 69 >> 1}),
            ({}, {}), ({}, {"r3": 69 << 1}),
            ({}, {}), ({}, {"r3": (69 >> 1) | 0x80000000}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
