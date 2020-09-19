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
            *[()]*4,
            (), (), ({}, {"r3": 69}), (),
            (), (), ({}, {"r3": (69<<8) + 69}), (),
            ({}, {"r3": (69<<8) + 69}), (),
            (), (), ({}, {"r3": (69<<16) + (69<<8) + 69}), (),
            (), (), ({}, {"r3": (69<<24) + (69<<16) + (69<<8) + 69}), (),
            (), (), ({}, {"r3": ((-42<<8) + 69) & 0xFFFFFFFF}), (),
            (), (), ({}, {"r3": (-5) & 0xFFFFFFFF}), (),
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
            *[()]*5,
            ({"re": 1}, {"rdy": 1, "data": 69}),
            ({"re": 0}, {"rdy": 0}),
            ({}, {}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_spl_event_fifo_overflow(self):
        prg = [
            POKE(SplW.EVENT_FIFO, 69),
            POKE(SplW.EVENT_FIFO, 70),
            POKE(SplW.EVENT_FIFO, 71),
            POKE(SplW.EVENT_FIFO, 72),
            POKE(SplW.EVENT_FIFO, 73),
            POKE(SplW.EVENT_FIFO, 74),
        ]
        sets = {"re": self.tb.i_event_re}
        chks = {"rdy": self.tb.o_event_valid,
                "data": self.tb.o_event,
                "pc": self.core.prg_ctl.o_fetch_addr}
        vals = [
            *[()]*5,
            ({}, {"rdy": 1, "pc": 3}), (),
            ({}, {"rdy": 1, "pc": 4}), (),
            ({}, {"rdy": 1, "pc": 5}), (),
            ({}, {"rdy": 1, "pc": 5}), (),
            ({"re": 1}, {"rdy": 1, "pc": 5, "data": 69}), ({"re": 0}, {}),
            ({}, {"rdy": 1, "pc": 6}), (),
            ({}, {"rdy": 1, "pc": 6}), (),
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
            *[()]*5,
            ({}, {"addr": 69, "data": 5, "we": 1}), (),
            ({}, {"addr": 70, "data": 6, "we": 1}), (),
            ({}, {"addr": 71, "we": 0}), (),
            ({}, {"addr": 42, "data": 7, "we": 1}), (),
            ({}, {"addr": 43, "we": 0}), (),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_spl_match_info(self):
        prg = [
            # reset code
            POKE(SplW.TMPA, 100),
            POKE(SplW.TMPB, 101),
            POKE(SplW.MATCH_ENABLE, 1),
            # event type 0 code (not used in this test)
            *[BRANCH(0)]*8,
            # event type 1 code
            COPY(3, SplR.TMPA),
            COPY(3, SplR.MATCH_TYPE),
            COPY(3, SplR.MATCH_CYCLE_COUNT),
            COPY(3, SplR.MATCH_ADDR),
            COPY(3, SplR.MATCH_DATA),
            BRANCH(0),
            BRANCH(0),
            BRANCH(0),
            # event type 2 code
            COPY(3, SplR.TMPB),
            COPY(3, SplR.MATCH_TYPE),
            COPY(3, SplR.MATCH_CYCLE_COUNT),
            COPY(3, SplR.MATCH_ADDR),
            COPY(3, SplR.MATCH_DATA),
            BRANCH(0),
            BRANCH(0),
            BRANCH(0),
        ]
        sets = {"mt": self.tb.i_match_info.match_type,
                "mc": self.tb.i_match_info.cycle_count,
                "ma": self.tb.i_match_info.addr,
                "md": self.tb.i_match_info.data,
                "we": self.tb.i_match_we}
        chks = {"r3": self.tb.reg_mem[3],
                "pc": self.core.prg_ctl.o_fetch_addr}
        vals = [
            ({"mt": 1, "mc": 2, "ma": 3, "md": 4, "we": 1}, {"pc": 0}),
            ({"we": 0}, {"pc": 1}), (),
            ({}, {"pc": 2}), ({}, {"pc": 2}),
            ({}, {"pc": 3}), (),
            ({}, {"pc": 4}), (),
            ({}, {"pc": 0}), (),

            ({"mt": 1, "mc": 2, "ma": 3, "md": 4, "we": 1}, {"pc": 0}),
            ({"we": 0}, {"pc": 0}), (), (),
            ({}, {"pc": 12}), ({}, {"pc": 12}),
            ({}, {"pc": 13}), ({}, {"pc": 13}),
            ({}, {"pc": 14,  "r3": 100}), (),
            ({}, {"pc": 15, "r3": 1}), (),
            ({}, {"pc": 16, "r3": 2}), (),
            ({}, {"pc": 17, "r3": 3}), (),
            ({}, {"pc": 0, "r3": 4}), (),
            ({}, {"pc": 0}), (),

            ({"mt": 2, "mc": 5, "ma": 6, "md": 7, "we": 1}, {"pc": 0}),
            ({"we": 0}, {"pc": 0}), (), (),
            ({}, {"pc": 20}), ({}, {"pc": 20}),
            ({}, {"pc": 21}), ({}, {"pc": 21}),
            ({}, {"pc": 22, "r3": 101}), (),
            ({}, {"pc": 23, "r3": 2}), (),
            ({}, {"pc": 24, "r3": 5}), (),
            ({}, {"pc": 25, "r3": 6}), (),
            ({}, {"pc": 0, "r3": 7}), (),
            ({}, {"pc": 0}), (),

            ({"mt": 1, "mc": 2, "ma": 3, "md": 4, "we": 1}, {"pc": 0}),
            ({"mt": 2, "mc": 5, "ma": 6, "md": 7}, {"pc": 0}),
            ({"we": 0}, {"pc": 0}), (),
            ({}, {"pc": 12}), ({}, {"pc": 12}),
            ({}, {"pc": 13}), ({}, {"pc": 13}),
            ({}, {"pc": 14, "r3": 100}), (),
            ({}, {"pc": 15, "r3": 1}), (),
            ({}, {"pc": 16, "r3": 2}), (),
            ({}, {"pc": 17, "r3": 3}), (),
            ({}, {"pc": 20, "r3": 4}), (),
            ({}, {"pc": 21, "r3": 4}), (),
            ({}, {"pc": 22, "r3": 101}), (),
            ({}, {"pc": 23, "r3": 2}), (),
            ({}, {"pc": 24, "r3": 5}), (),
            ({}, {"pc": 25, "r3": 6}), (),
            ({}, {"pc": 0, "r3": 7}), (),
            ({}, {"pc": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_spl_mod_offset(self):
        prg = [
            POKE(SplW.MATCH_ENABLE, 1),
            POKE(SplW.TMPA, 69),
            POKE(SplW.TMPB, 42),

            COPY(3, SplR.TMPA),
            COPY(4, SplR.TMPB),
            POKE(SplW.MOFF_WR_TEMP, 1),
            MODIFY(3, Mod.COPY),

            COPY(4, SplR.TMPB),
            POKE(SplW.MOFF_RD_TEMP, 1),
            MODIFY(3, Mod.COPY),

            POKE(SplW.MOFF_RD_HOLD, 1),
            POKE(SplW.MOFF_WR_HOLD, 2),
            COPY(3, SplR.TMPA),
            MODIFY(2, Mod.COPY),

            COPY(4, SplR.TMPB),
            MODIFY(2, Mod.COPY),
            COPY(4, SplR.TMPB),
            *[BRANCH(0)]*6,
            MODIFY(2, Mod.COPY),
        ]
        sets = {"mt": self.tb.i_match_info.match_type,
                "we": self.tb.i_match_we}
        chks = {"r3": self.tb.reg_mem[3],
                "r4": self.tb.reg_mem[4]}
        vals = [
            ({}, {}), (),
            ({}, {}), (),
            ({"mt": 3, "we": 1}, {}),
            ({"we": 0}, {}), (),
            ({}, {}), (),
            ({}, {}), (),

            ({}, {"r3": 69}), (),
            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 69}), (),

            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 42, "r4": 42}), (),

            ({}, {"r3": 42, "r4": 42}), (),
            ({}, {"r3": 42, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 69}), (),

            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 69}), (),
            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 42}), (),
            ({}, {"r3": 69, "r4": 42}), (),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_spl_branch_ind(self):
        prg = [
            BRANCH(2),
            POKE(SplW.BRANCH_IND_TARGET, 5),
            BRANCH(0),
            BRANCH(0),
            BRANCH(7),
            BRANCH(0),
            COPY(3, SplR.CURR_PC),
            COPY(SplW.BRANCH_IND_TARGET, 3),
            BRANCH(0),
        ]
        sets = {}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr}
        vals = [
            ({}, {"pc": 0}),
            ({}, {"pc": 1}), ({}, {"pc": 1}),
            ({}, {"pc": 2}), ({}, {"pc": 2}),
            ({}, {"pc": 3}), ({}, {"pc": 3}),
            ({}, {"pc": 5}), ({}, {"pc": 5}),
            ({}, {"pc": 7}), ({}, {"pc": 7}),
            ({}, {"pc": 8}), ({}, {"pc": 8}),
            ({}, {"pc": 9}), ({}, {"pc": 9}),
            ({}, {"pc": 7}), ({}, {"pc": 7}),
            ({}, {"pc": 8}), ({}, {"pc": 8}),
            ({}, {"pc": 9}), ({}, {"pc": 9}),
            # and so on
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
