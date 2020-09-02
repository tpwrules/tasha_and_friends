# test various features of various special units

from nmigen import *

from .test import SimTest, cycle_test
from ..isa import *

import unittest

class TestSpecial(SimTest, unittest.TestCase):
    @cycle_test
    def test_spl_imm(self):
        prg = [
            POKE(SplW.IMM_B0, 69),  COPY(3, SplR.IMM_VAL),
            POKE(SplW.IMM_B1, 69),  COPY(3, SplR.IMM_VAL),
            COPY(3, SplR.IMM_VAL),
            POKE(SplW.IMM_B2, 69),  COPY(3, SplR.IMM_VAL),
            POKE(SplW.IMM_B3, 69),  COPY(3, SplR.IMM_VAL),
            POKE(SplW.IMM_B1, -42), COPY(3, SplR.IMM_VAL),
            POKE(SplW.IMM_B0, -5),  COPY(3, SplR.IMM_VAL),
        ]
        sets = {}
        chks = {"r3": self.tb.reg_mem[3]}
        vals = [
            *[({}, {})]*3,
            ({}, {}), ({}, {"r3": 69}),
            ({}, {}), ({}, {"r3": (69<<8) + 69}),
            ({}, {"r3": (69<<8) + 69}),
            ({}, {}), ({}, {"r3": (69<<16) + (69<<8) + 69}),
            ({}, {}), ({}, {"r3": (69<<24) + (69<<16) + (69<<8) + 69}),
            ({}, {}), ({}, {"r3": ((-42<<8) + 69) & 0xFFFFFFFF}),
            ({}, {}), ({}, {"r3": (-5) & 0xFFFFFFFF}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
