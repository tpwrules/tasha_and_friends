# test basic logic of the core to ensure that it generates the correct control
# signals for all the instructions. does not check the actual data processing of
# the instructions themselves (except what POKE writes).

from nmigen import *

from .test import SimCoreTest, cycle_test
from ..isa import *
from ..alu import Flags

import unittest

class TestCore(SimCoreTest, unittest.TestCase):
    @cycle_test
    def test_BRANCH_logic(self):
        prg = [
            BRANCH(6),
            BRANCH(1),
            BRANCH(10, Cond.NEVER),
            BRANCH(2),
            BRANCH(4),
            BRANCH(5),
        ]
        sets = {}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr}
        vals = [
            # make sure all the branches get followed
            ({}, {"pc": 0}),
            ({}, {"pc": 1}),
            ({}, {"pc": 6}),
            ({}, {"pc": 5}),
            ({}, {"pc": 4}),
            ({}, {"pc": 2}),
            ({}, {"pc": 1}),
            ({}, {"pc": 6}),
            ({}, {"pc": 5}),
            ({}, {"pc": 4}),
            ({}, {"pc": 2}),
            # and so on
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_BRANCH_flag_logic(self):
        prg = [
            BRANCH(0, Cond.GTU),
            BRANCH(0, Cond.LEU),
            BRANCH(0, Cond.GES),
            BRANCH(0, Cond.LTS),
            BRANCH(0, Cond.GTS),
            BRANCH(0, Cond.LES),
            BRANCH(0, Cond.Z0),
            BRANCH(0, Cond.Z1),
            BRANCH(0, Cond.S0),
            BRANCH(0, Cond.S1),
            BRANCH(0, Cond.C0),
            BRANCH(0, Cond.C1),
            BRANCH(0, Cond.V0),
            BRANCH(0, Cond.V1),
        ]
        sets = {"vcsz": self.core.i_flags}
        chks = {"pc": self.core.prg_ctl.o_fetch_addr}
        vals = [
            ({},               {"pc": 0}),
            ({"vcsz": 0b0001}, {"pc": 1}),
            ({"vcsz": 0b0100}, {"pc": 2}),
            ({"vcsz": 0b1000}, {"pc": 3}),
            ({"vcsz": 0b0000}, {"pc": 4}),
            ({"vcsz": 0b0010}, {"pc": 5}),
            ({"vcsz": 0b0000}, {"pc": 6}),
            ({"vcsz": 0b0001}, {"pc": 7}),
            ({"vcsz": 0b0000}, {"pc": 8}),
            ({"vcsz": 0b0010}, {"pc": 9}),
            ({"vcsz": 0b0000}, {"pc": 10}),
            ({"vcsz": 0b0100}, {"pc": 11}),
            ({"vcsz": 0b0000}, {"pc": 12}),
            ({"vcsz": 0b1000}, {"pc": 13}),
            ({"vcsz": 0b0000}, {"pc": 14}),
            ({"vcsz": 0b0000}, {"pc": 15}),
            ({"vcsz": 0b0000}, {"pc": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_COPY_to_spl_logic(self):
        prg = [
            COPY(SplW.TMPA, 1),
            COPY(SplW.TMPB, 2),
            COPY(SplW.TMPA, 3),
        ]
        sets = {}
        chks = {"swaddr": self.core.o_spl_waddr,
                "sre": self.core.o_spl_re,
                "swe": self.core.o_spl_we,
                "rraddr": self.core.o_reg_raddr,
                "rre": self.core.o_reg_re,
                "rwe": self.core.o_reg_we}
        vals = [
            # program is starting
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 0}),
            # decoding the first COPY and reading from the regular reg
            ({}, {"sre": 0, "swe": 0, "rre": 1, "rwe": 0,
                  "rraddr": 1}),
            # writing the value to the special register and decoding the next
            ({}, {"sre": 0, "swe": 1, "rre": 1, "rwe": 0,
                  "swaddr": SplW.TMPA, "rraddr": 2}),
            # again
            ({}, {"sre": 0, "swe": 1, "rre": 1, "rwe": 0,
                  "swaddr": SplW.TMPB, "rraddr": 3}),
            # writing the last value to the special register
            ({}, {"sre": 0, "swe": 1, "rre": 0, "rwe": 0,
                  "swaddr": SplW.TMPA}),
            # program stopped, no more activity
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_COPY_from_spl_logic(self):
        prg = [
            COPY(1, SplR.TMPB),
            COPY(2, SplR.TMPA),
            COPY(3, SplR.TMPB),
        ]
        sets = {}
        chks = {"sraddr": self.core.o_spl_raddr,
                "sre": self.core.o_spl_re,
                "swe": self.core.o_spl_we,
                "rwaddr": self.core.o_reg_waddr,
                "rre": self.core.o_reg_re,
                "rwe": self.core.o_reg_we}
        vals = [
            # program is starting
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 0}),
            # decoding the first COPY and reading from the special reg
            ({}, {"sre": 1, "swe": 0, "rre": 0, "rwe": 0,
                  "sraddr": SplR.TMPB}),
            # writing the value to the regular register and decoding the next
            ({}, {"sre": 1, "swe": 0, "rre": 0, "rwe": 1,
                  "sraddr": SplR.TMPA, "rwaddr": 1}),
            # again
            ({}, {"sre": 1, "swe": 0, "rre": 0, "rwe": 1,
                  "sraddr": SplR.TMPB, "rwaddr": 2}),
            # writing the last value to the regular register
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 1,
                  "rwaddr": 3}),
            # program stopped, no more activity
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_POKE_logic(self):
        prg = [
            POKE(SplW.TMPA, 256),
            POKE(SplW.TMPB, 4),
            POKE(SplW.TMPA, 27),
        ]
        sets = {}
        chks = {"swaddr": self.core.o_spl_waddr,
                "swdata": self.core.o_spl_wdata,
                "swe": self.core.o_spl_we}
        vals = [
            # program is starting
            ({}, {"swe": 0}),
            # decoding the first POKE: nothing til next cycle
            ({}, {"swe": 0}),
            # poking the value to the special register
            ({}, {"swe": 1, "swaddr": SplW.TMPA, "swdata": 0xFFFFFF00}),
            # again
            ({}, {"swe": 1, "swaddr": SplW.TMPB, "swdata": 4}),
            # poking the last value
            ({}, {"swe": 1, "swaddr": SplW.TMPA, "swdata": 27}),
            # program stopped, no more activity
            ({}, {"swe": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_MODIFY_logic(self):
        prg = [
            MODIFY(Mod.COPY, 1),
            MODIFY(Mod.COPY, 2),
            MODIFY(Mod.COPY, 3),
        ]
        sets = {}
        chks = {"rraddr": self.core.o_reg_raddr,
                "rwaddr": self.core.o_reg_waddr,
                "rre": self.core.o_reg_re,
                "rwe": self.core.o_reg_we,
                "mod": self.core.o_mod,
                "type": self.core.o_mod_type}
        vals = [
            # program is starting
            ({}, {"rre": 0, "rwe": 0, "mod": 0}),
            # decoding the first MODIFY and reading its register
            ({}, {"rre": 1, "rwe": 0, "mod": 0,
                  "rraddr": 1}),
            # doing the modification and writing it back
            ({}, {"rre": 1, "rwe": 1, "mod": 1,
                  "rraddr": 2, "rwaddr": 1, "type": Mod.COPY}),
            # again
            ({}, {"rre": 1, "rwe": 1, "mod": 1,
                  "rraddr": 3, "rwaddr": 2, "type": Mod.COPY}),
            # modifying the last register
            ({}, {"rre": 0, "rwe": 1, "mod": 1,
                  "rwaddr": 3, "type": Mod.COPY}),
            # program stopped, no more activity
            ({}, {"rre": 0, "rwe": 0, "mod": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_mixed_logic(self):
        prg = [
            MODIFY(Mod.COPY, 1),
            COPY(SplW.TMPA, 2),
            BRANCH(7),
            # 4
            POKE(SplW.TMPB, 3),
            COPY(4, SplR.TMPA),
            BRANCH(0),
            # 7
            POKE(SplW.TMPA, 5),
            MODIFY(Mod.COPY, 6),
            BRANCH(4),
        ]
        sets = {}
        chks = {"rraddr": self.core.o_reg_raddr,
                "rwaddr": self.core.o_reg_waddr,
                "rre": self.core.o_reg_re,
                "rwe": self.core.o_reg_we,
                "sraddr": self.core.o_spl_raddr,
                "swaddr": self.core.o_spl_waddr,
                "swdata": self.core.o_spl_wdata,
                "sre": self.core.o_spl_re,
                "swe": self.core.o_spl_we,
                "mod": self.core.o_mod,
                "type": self.core.o_mod_type}
        vals = [
            # program is starting
            ({}, {"rre": 0, "rwe": 0, "sre": 0, "swe": 0, "mod": 0}),
            # fetch: MODIFY
            ({}, {"rre": 1, "rwe": 0, "sre": 0, "swe": 0, "mod": 0,
                  "rraddr": 1}),
            # fetch: COPY, exec: MODIFY
            ({}, {"rre": 1, "rwe": 1, "sre": 0, "swe": 0, "mod": 1,
                  "rraddr": 2, "rwaddr": 1, "type": Mod.COPY}),
            # fetch: BRANCH, exec: COPY
            ({}, {"rre": 0, "rwe": 0, "sre": 0, "swe": 1, "mod": 0,
                  "swaddr": SplW.TMPA}),
            # fetch: POKE, exec: BRANCH
            ({}, {"rre": 0, "rwe": 0, "sre": 0, "swe": 0, "mod": 0}),
            # fetch: MODIFY, exec: POKE
            ({}, {"rre": 1, "rwe": 0, "sre": 0, "swe": 1, "mod": 0,
                  "rraddr": 6, "swaddr": SplW.TMPA, "swdata": 5}),
            # fetch: BRANCH, exec: MODIFY
            ({}, {"rre": 0, "rwe": 1, "sre": 0, "swe": 0, "mod": 1,
                  "rwaddr": 6, "type": Mod.COPY}),
            # fetch: POKE, exec: BRANCH
            ({}, {"rre": 0, "rwe": 0, "sre": 0, "swe": 0, "mod": 0}),
            # fetch: COPY, exec: POKE
            ({}, {"rre": 0, "rwe": 0, "sre": 1, "swe": 1, "mod": 0,
                  "sraddr": SplR.TMPA, "swaddr": SplW.TMPB, "swdata": 3}),
            # fetch: BRANCH, exec: COPY
            ({}, {"rre": 0, "rwe": 1, "sre": 0, "swe": 0, "mod": 0,
                  "rwaddr": 4}),
            # program stopped, no more activity
            ({}, {"rre": 0, "rwe": 0, "sre": 0, "swe": 0, "mod": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

if __name__ == "__main__":
    unittest.main()
