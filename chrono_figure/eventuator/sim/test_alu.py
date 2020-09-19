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
            COPY(3, SplR.TMPA), MODIFY(3, Mod.ADD_0),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.INC),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.ADD_B0),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.ADD_B1),
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3]}
        vals = [
            *[()]*10,
            (), (), ({}, {"r3": 69}), (),
            (), (), ({}, {"r3": 70}), (),
            (), (), ({}, {"r3": 71}), (),
            (), (), ({}, {"r3": 72}), (),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_ALU_operations(self):
        prg = [
            POKE(SplW.TMPA, 69),
            POKE(SplW.ALU_B0, 43),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.AND_B0),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.OR_B0),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.XOR_B0),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.ADD_B0),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.SUB_B0),

            COPY(3, SplR.TMPA), MODIFY(3, Mod.SHIFT_LEFT),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.SHIFT_RIGHT),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.ROTATE_LEFT),
            COPY(3, SplR.TMPA), MODIFY(3, Mod.ROTATE_RIGHT),
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3]}
        vals = [
            *[()]*8,
            (), (), ({}, {"r3": 69 & 43}), (),
            (), (), ({}, {"r3": 69 | 43}), (),
            (), (), ({}, {"r3": 69 ^ 43}), (),
            (), (), ({}, {"r3": 69 + 43}), (),
            (), (), ({}, {"r3": 69 - 43}), (),

            (), (), ({}, {"r3": 69 << 1}), (),
            (), (), ({}, {"r3": 69 >> 1}), (),
            (), (), ({}, {"r3": 69 << 1}), (),
            (), (), ({}, {"r3": (69 >> 1) | 0x80000000}),
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
        chks = {"pc": self.core.prg_ctl.o_fetch_addr}
        prg = []
        vals = []
        pc = 0
        for a, b, *conds in tests:
            vals.extend(((({"r3": a, "b0": b}, {"pc": pc})), ()))
            prg.append(MODIFY(3, Mod.CMP_B0))
            pc += 1
            for cond in conds:
                prg.append(BRANCH(0, Cond(cond ^ 1)))
                vals.extend(((({}, {"pc": pc})), ()))
                pc += 1
        vals.extend(((({}, {"pc": pc})), ()))
        vals.extend(((({}, {"pc": pc+1})), ()))
        vals.extend(((({}, {"pc": 0})), ()))

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_ALU_flags_frontend(self):
        prg = [
            # high 4 bits: 1 = preserve value, 0 = update value
            # low 4 bits (if not preserved): 1 = set value, 0 = clear value
            POKE(SplW.ALU_FLAGS, 0b0000_0000),
            POKE(SplW.ALU_FLAGS, 0b0000_0101),
            POKE(SplW.ALU_FLAGS, 0b0101_1010),
            POKE(SplW.ALU_FLAGS, 0b1111_0000),
            COPY(3, SplR.ALU_FLAGS),
            POKE(SplW.ALU_B0, 0b1111),
            POKE(SplW.ALU_FLAGS, 0b0000_0000),
            MODIFY(3, Mod.CMP_B0),
            POKE(SplW.ALU_FLAGS, 0b0000_0000),
            POKE(SplW.ALU_FLAGS, 0b1111_0000),
        ]
        sets = {}
        chks = {"vcsz": self.core.i_flags}
        vals = [
            (), (), (), (),
            ({}, {"vcsz": 0b0000}), (),
            ({}, {"vcsz": 0b0101}), (),
            ({}, {"vcsz": 0b1111}), (),
            ({}, {"vcsz": 0b1111}), (),
            (), (), (), (),
            ({}, {"vcsz": 0b0000}), (),
            ({}, {"vcsz": 0b0101}), (),
            ({}, {"vcsz": 0b0000}), (),
            ({}, {"vcsz": 0b0000}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
