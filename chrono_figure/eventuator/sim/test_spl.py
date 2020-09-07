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

    @cycle_test
    def test_spl_event_fifo(self):
        prg = [
            POKE(SplW.EVENT_FIFO, 69),
        ]
        sets = {"re": self.tb.i_event_re}
        chks = {"rdy": self.tb.o_event_valid,
                "data": self.tb.o_event}
        vals = [
            ({}, {}),
            ({}, {}),
            ({}, {}),
            ({}, {}),
            ({"re": 1}, {"rdy": 1, "data": 69}),
            ({"re": 0}, {"rdy": 0}),
            ({}, {}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_spl_match_config(self):
        prg = [
            POKE(SplW.MATCH_CONFIG_ADDR, 69),
            POKE(SplW.MATCH_CONFIG_DATA, 5),
            POKE(SplW.MATCH_CONFIG_DATA, 6),
            POKE(SplW.MATCH_CONFIG_ADDR, 42),
            POKE(SplW.MATCH_CONFIG_DATA, 7),
        ]
        sets = {}
        chks = {"data": self.ev.o_match_config,
                "addr": self.ev.o_match_config_addr,
                "we": self.ev.o_match_config_we}
        vals = [
            ({}, {}),
            ({}, {}),
            ({}, {}),
            ({}, {"addr": 69, "data": 5, "we": 1}),
            ({}, {"addr": 70, "data": 6, "we": 1}),
            ({}, {"addr": 71}),
            ({}, {"addr": 42, "data": 7, "we": 1}),
            ({}, {"addr": 43}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
