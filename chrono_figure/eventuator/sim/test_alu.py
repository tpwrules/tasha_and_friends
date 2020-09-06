# test the ALU functions

from nmigen import *

from .test import SimTop, SimTest, cycle_test
from ..isa import *

import unittest

class TestALU(SimTest, unittest.TestCase):
    def setUp(self):
        # the comparison test needs a bunch of program memory
        self.tb = SimTop(match_d=4, event_d=4, prg_d=128, reg_d=32)
        self.ev = self.tb.ev
        self.core = self.tb.ev.core

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

    @cycle_test
    def test_ALU_comparisons(self):
        # tuple of A, B, and which branch(es) should succeed after CMP(A, B)
        tests = [
            (5, 5,   Cond.EQ, Cond.LEU, Cond.GEU, Cond.LES, Cond.GES),
            (-5, -5, Cond.EQ, Cond.LEU, Cond.GEU, Cond.LES, Cond.GES),

            (5, 6,   Cond.NE, Cond.LTU, Cond.LEU, Cond.LTS, Cond.LES),
            (-5, 6,  Cond.NE, Cond.GTU, Cond.GEU, Cond.LTS, Cond.LES),
            (5, -6,  Cond.NE, Cond.LTU, Cond.LEU, Cond.GTS, Cond.GES),
            (-5, -6, Cond.NE, Cond.GTU, Cond.GEU, Cond.GTS, Cond.GES),

            (6, 5,   Cond.NE, Cond.GTU, Cond.GEU, Cond.GTS, Cond.GES),
            (-6, 5,  Cond.NE, Cond.GTU, Cond.GEU, Cond.LTS, Cond.LES),
            (6, -5,  Cond.NE, Cond.LTU, Cond.LEU, Cond.GTS, Cond.GES),
            (-6, -5, Cond.NE, Cond.LTU, Cond.LEU, Cond.LTS, Cond.LES),
        ]

        sets = {"r3": self.tb.reg_mem[3],
                "b0": self.ev.spl_alu_frontend.o_B0}
        chks = {"pc": self.core.o_prg_addr}
        prg = []
        vals = []
        pc = 1
        for a, b, *conds in tests:
            vals.append(({"r3": a, "b0": b}, {"pc": pc}))
            prg.append(MODIFY(Mod.CMP_B0, 3))
            pc += 1
            for cond in conds:
                prg.append(BRANCH(0, Cond(cond ^ 1)))
                vals.append(({}, {"pc": pc}))
                pc += 1
        vals.append(({}, {"pc": pc}))
        vals.append(({}, {"pc": 0}))

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
