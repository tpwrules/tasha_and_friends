# test basic operation of the core to ensure that it generates the correct
# control signals for all the instructions. does not check the actual data
# processing of the instructions themselves.

from nmigen import *

from .test import SimCoreTest, cycle_test
from .top import SimTop
from ..instructions import *

import unittest

class TestCore(SimCoreTest, unittest.TestCase):
    @cycle_test
    def test_BRANCH(self):
        prg = [
            BRANCH(5),
            BRANCH(1),
            BRANCH(2),
            BRANCH(3),
            BRANCH(4),
        ]
        sets = {}
        chks = {"pc": self.core.o_prg_addr}
        vals = [
            # make sure all the branches get followed
            ({}, {"pc": 1}),
            ({}, {"pc": 5}),
            ({}, {"pc": 4}),
            ({}, {"pc": 3}),
            ({}, {"pc": 2}),
            ({}, {"pc": 1}),
            ({}, {"pc": 5}),
            ({}, {"pc": 4}),
            ({}, {"pc": 3}),
            # and so on
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_COPY_to_spl(self):
        prg = [
            COPY(Special.TEST, 1),
            COPY(Special.TEST, 2),
            COPY(Special.TEST, 3),
        ]
        sets = {}
        chks = {"saddr": self.core.o_spl_addr,
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
                  "saddr": Special.TEST, "rraddr": 2}),
            # again
            ({}, {"sre": 0, "swe": 1, "rre": 1, "rwe": 0,
                  "saddr": Special.TEST, "rraddr": 3}),
            # writing the last value to the special register
            ({}, {"sre": 0, "swe": 1, "rre": 0, "rwe": 0,
                  "saddr": Special.TEST}),
            # program stopped, no more activity
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_COPY_from_spl(self):
        prg = [
            COPY(1, Special.TEST),
            COPY(2, Special.TEST),
            COPY(3, Special.TEST),
        ]
        sets = {}
        chks = {"saddr": self.core.o_spl_addr,
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
                  "saddr": Special.TEST}),
            # writing the value to the regular register and decoding the next
            ({}, {"sre": 1, "swe": 0, "rre": 0, "rwe": 1,
                  "saddr": Special.TEST, "rwaddr": 1}),
            # again
            ({}, {"sre": 1, "swe": 0, "rre": 0, "rwe": 1,
                  "saddr": Special.TEST, "rwaddr": 2}),
            # writing the last value to the regular register
            ({}, {"sre": 0, "swe": 0, "rre": 0, "rwe": 1,
                  "rwaddr": 3}),
            # program stopped, no more activity
            ({},                 {"sre": 0, "swe": 0,
                                  "rre": 0, "rwe": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_POKE(self):
        prg = [
            POKE(Special.TEST, 256),
            POKE(Special.TEST, 4),
            POKE(Special.TEST, 27),
        ]
        sets = {}
        chks = {"saddr": self.core.o_spl_addr,
                "sdata": self.core.o_spl_data,
                "swe": self.core.o_spl_we}
        vals = [
            # program is starting
            ({}, {"swe": 0}),
            # decoding the first POKE: nothing til next cycle
            ({}, {"swe": 0}),
            # poking the value to the special register
            ({}, {"swe": 1, "saddr": Special.TEST, "sdata": 0xFFFFFF00}),
            # again
            ({}, {"swe": 1, "saddr": Special.TEST, "sdata": 4}),
            # poking the last value
            ({}, {"swe": 1, "saddr": Special.TEST, "sdata": 27}),
            # program stopped, no more activity
            ({}, {"swe": 0}),
        ]

        return sets, chks, vals, self.proc_start_prg(prg)

    @cycle_test
    def test_MODIFY(self):
        prg = [
            MODIFY(Mod.COPY, 1),
            MODIFY(Mod.COPY, 2),
            MODIFY(Mod.COPY, 3),
        ]
        sets = {"s": self.core.i_ctl_start,
                "spc": self.core.i_ctl_pc}
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

if __name__ == "__main__":
    unittest.main()
