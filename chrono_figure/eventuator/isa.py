from enum import IntEnum

from .special_map import SplR, SplW, SPL_WIDTH

INSN_WIDTH = 18
PC_WIDTH = 12
COND_WIDTH = 4
DATA_WIDTH = 32
REGS_WIDTH = 8

class InsnCode(IntEnum):
    BRANCH = 0
    COPY = 1
    POKE = 2
    MODIFY = 3

class Cond(IntEnum): # low bit is set -> invert condition
    # like it says
    ALWAYS = 0 # must always be 0!
    NEVER = 1
    # not C or Z
    LEU = 2
    GTU = 3
    # S xor V
    LTS = 4
    GES = 5
    # S xor V or Z
    LES = 6
    GTS = 7
    # Z = 1
    EQ = 8
    NE = 9
    Z1 = 8
    Z0 = 9
    # S = 1
    MI = 10
    PL = 11
    S1 = 10
    S0 = 11
    # C = 1
    CS = 12
    CC = 13
    GEU = 12
    LTU = 13
    C1 = 12
    C0 = 13
    # V = 1
    VS = 14
    VC = 15
    V1 = 14
    V0 = 15

class Mod(IntEnum):
    COPY = 1

    # ALU mod code encodings
    # 11wssooo
    # w: 1 if result should be written to destination (otherwise not modified)
    # ss: B input source (or shift mode)
    #   0b00: 0 (or shift left)
    #   0b01: 1 (or shift right)
    #   0b10: B0 (or rotate left)
    #   0b11: B1 (or rotate right)
    # ooo: operation code
    #   0b000: AND
    #   0b001: OR
    #   0b010: XOR
    #   0b011: undefined
    #   0b100: add
    #   0b101: subtract
    #   0b110: shift/rotate (action selected by B input)
    #   0b111: undefined

    # NOP           = 0b110_00_000
    TEST_LSB        = 0b110_01_000
    TEST_B0         = 0b110_10_000
    TEST_B1         = 0b110_11_000

    TEST_ZERO       = 0b110_00_001
    # NOP           = 0b110_01_001
    # NOP           = 0b110_10_001
    # NOP           = 0b110_11_001

    # NOP           = 0b110_00_010
    # NOP           = 0b110_01_010
    # NOP           = 0b110_10_010
    # NOP           = 0b110_11_010

    # NOP           = 0b110_00_100
    # NOP           = 0b110_01_100
    # NOP           = 0b110_10_100
    # NOP           = 0b110_11_100

    # NOP           = 0b110_00_101
    CMP_1           = 0b110_01_101
    CMP_B0          = 0b110_10_101
    CMP_B1          = 0b110_11_101

    # NOP           = 0b110_00_110
    # NOP           = 0b110_01_110
    # NOP           = 0b110_10_110
    # NOP           = 0b110_11_110

    ZERO            = 0b111_00_000
    GET_LSB         = 0b111_01_000
    AND_B0          = 0b111_10_000
    AND_B1          = 0b111_11_000

    # NOP           = 0b111_00_001
    SET_LSB         = 0b111_01_001
    OR_B0           = 0b111_10_001
    OR_B1           = 0b111_11_001

    # NOP           = 0b111_00_010
    FLIP_LSB        = 0b111_01_010
    XOR_B0          = 0b111_10_010
    XOR_B1          = 0b111_11_010

    ADD_0           = 0b111_00_100
    INC             = 0b111_01_100
    ADD_B0          = 0b111_10_100
    ADD_B1          = 0b111_11_100

    SUB_0           = 0b111_00_101
    DEC             = 0b111_01_101
    SUB_B0          = 0b111_10_101
    SUB_B1          = 0b111_11_101

    SHIFT_LEFT      = 0b111_00_110
    SHIFT_RIGHT     = 0b111_01_110
    ROTATE_LEFT     = 0b111_10_110
    ROTATE_RIGHT    = 0b111_11_110


# set the PC to the destination if the condition is true
class BRANCH:
    def __init__(self, dest, cond=Cond.ALWAYS):
        dest = int(dest)
        if dest < 0 or dest >= 2**PC_WIDTH:
            raise ValueError("dest pc {} out of range".format(dest))
        self.dest = dest

        if not isinstance(cond, Cond):
            raise ValueError("invalid condition")
        self.cond = cond

    def __int__(self):
        return ((int(InsnCode.BRANCH) << 16) + (int(self.cond) << 12)
            + self.dest)

    def __str__(self):
        return "BRANCH({}, {})".format(self.dest, str(self.cond))

# copy a special register to a regular register or vice versa
class COPY:
    def __init__(self, dest, src):
        dest_special = isinstance(dest, SplW)
        src_special = isinstance(src, SplR)
        if dest_special and src_special:
            raise ValueError("can't copy special to special")
        elif not dest_special and not src_special:
            raise ValueError("can't copy reg to reg")

        if dest_special:
            self.dir = 1
            self.dest = dest
            src = int(src)
            if src < 0 or src >= 2**REGS_WIDTH:
                raise ValueError("src reg {} out of range".format(src))
            if isinstance(dest, SplR):
                raise ValueError("can't write to SplR")
            self.src = src
        else:
            self.dir = 0
            dest = int(dest)
            if dest < 0 or dest >= 2**REGS_WIDTH:
                raise ValueError("dest reg {} out of range".format(dest))
            if isinstance(src, SplW):
                raise ValueError("can't read from SplW")
            self.dest = dest
            self.src = src

        self.code = InsnCode.COPY

    def __int__(self):
        n = (int(InsnCode.COPY) << 16) + (self.dir << 15)
        if self.dir == 1:
            return n + (int(self.dest) << 8) + self.src
        else:
            return n + (int(self.src) << 8) + self.dest

    def __str__(self):
        if self.dir == 1:
            return "COPY({}, {})".format(str(self.dest), self.src)
        else:
            return "COPY({}, {})".format(self.dest, str(self.src))

# write a 9-bit sign-extended value to a special register
class POKE:
    def __init__(self, special, val):
        if not isinstance(special, SplW):
            raise ValueError("can only poke SplW")
        self.special = special

        val = int(val)
        if val < -256 or val > 511:
            raise ValueError("val {} out of range".format(val))
        self.val = val

        self.code = InsnCode.POKE

    def __int__(self):
        return (int(InsnCode.POKE << 16) + ((self.val & 0x100) << 7)
            + (self.special << 8) + (self.val & 0xFF))

    def __str__(self):
        return "POKE({}, {})".format(str(self.special), self.val)

# do a read-modify-write operation on a register
class MODIFY:
    def __init__(self, mod, reg):
        if not isinstance(mod, Mod):
            raise ValueError("not a mod")
        self.mod = mod
        
        if reg < 0 or reg >= 2**REGS_WIDTH:
            raise ValueError("reg {} out of range".format(reg))
        self.reg = reg

        self.code = InsnCode.MODIFY

    def __int__(self):
        return (int(InsnCode.MODIFY << 16) + int(self.mod << 8) + self.reg)

    def __str__(self):
        return "MODIFY({}, {})".format(str(self.mod), self.reg)


if __name__ == "__main__":
    def ass(got, expected):
        if got != expected:
            raise AssertionError("expected {} but got {}".format(expected, got))
    print("Testing basic instruction encoding")
    i = BRANCH(0) # MUST BE ENCODED AS 0
    ass(hex(int(i)), "0x0")
    ass(str(i), "BRANCH(0, Cond.ALWAYS)")

    i = BRANCH(69)
    ass(hex(int(i)), "0x45")
    ass(str(i), "BRANCH(69, Cond.ALWAYS)")

    i = BRANCH(69, Cond.NEVER)
    ass(hex(int(i)), "0xf045")
    ass(str(i), "BRANCH(69, Cond.NEVER)")

    i = COPY(SplW.TMPA, 69)
    ass(hex(int(i)), "0x18045")
    ass(str(i), "COPY(SplW.TMPA, 69)")
    i = COPY(69, SplR.TMPB)
    ass(hex(int(i)), "0x10145")
    ass(str(i), "COPY(69, SplR.TMPB)")
    
    i = POKE(SplW.TMPB, 69)
    ass(hex(int(i)), "0x20145")
    ass(str(i), "POKE(SplW.TMPB, 69)")
    i = POKE(SplW.TMPB, -69)
    ass(hex(int(i)), "0x281bb")
    ass(str(i), "POKE(SplW.TMPB, -69)")
    i = POKE(SplW.TMPA, 269)
    ass(hex(int(i)), "0x2800d")
    ass(str(i), "POKE(SplW.TMPA, 269)")

    i = MODIFY(Mod.COPY, 69)
    ass(hex(int(i)), "0x30145")
    ass(str(i), "MODIFY(Mod.COPY, 69)")

    print("Passed")
