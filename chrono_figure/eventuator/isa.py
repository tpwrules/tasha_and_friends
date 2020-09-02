from enum import IntEnum

INSN_WIDTH = 18
PC_WIDTH = 12
COND_WIDTH = 4
DATA_WIDTH = 32
REGS_WIDTH = 8
SPL_WIDTH = 7

class InsnCode(IntEnum):
    BRANCH = 0
    COPY = 1
    POKE = 2
    MODIFY = 3

class Cond(IntEnum):
    ALWAYS = 0
    NEVER = 15

class SplR(IntEnum):
    TMPA = 0
    TMPB = 1

class SplW(IntEnum):
    TMPA = 0
    TMPB = 1

class Mod(IntEnum):
    COPY = 1

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
