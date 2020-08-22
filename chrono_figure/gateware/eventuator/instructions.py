from enum import IntEnum

from .widths import *

class InsnCode(IntEnum):
    BRANCH = 0
    COPY = 1
    POKE = 2
    MODIFY = 3

class Condition(IntEnum):
    ALWAYS = 1

class Special(IntEnum):
    TEST = 1

class Mod(IntEnum):
    COPY = 1

# set the PC to the destination if the condition is true
class BRANCH:
    def __init__(self, dest, condition=Condition.ALWAYS):
        dest = int(dest)
        if dest < 0 or dest >= 2**PC_WIDTH:
            raise ValueError("dest pc {} out of range".format(dest))
        self.dest = dest

        if not isinstance(condition, Condition):
            raise ValueError("invalid condition")
        self.condition = condition

    def __int__(self):
        return ((int(InsnCode.BRANCH) << 16) + (int(self.condition) << 12)
            + self.dest)

    def __str__(self):
        return "BRANCH({}, {})".format(self.dest, str(self.condition))

# copy a special register to a regular register or vice versa
class COPY:
    def __init__(self, dest, src):
        dest_special = isinstance(dest, Special)
        src_special = isinstance(src, Special)
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
            self.src = src
        else:
            self.dir = 0
            dest = int(dest)
            if dest < 0 or dest >= 2**REGS_WIDTH:
                raise ValueError("dest reg {} out of range".format(dest))
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
        if not isinstance(special, Special):
            raise ValueError("can only poke special")
        self.special = special

        val = int(val)
        if val < -256 or val > 255:
            raise ValueError("val {} out of range".format(val))
        self.val = val

        self.code = InsnCode.POKE

    def __int__(self):
        return (int(InsnCode.POKE << 16) + ((self.val < 0) << 15)
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
    i = BRANCH(69)
    ass(hex(int(i)), "0x1045")
    ass(str(i), "BRANCH(69, Condition.ALWAYS)")

    i = COPY(Special.TEST, 69)
    ass(hex(int(i)), "0x18145")
    ass(str(i), "COPY(Special.TEST, 69)")
    i = COPY(69, Special.TEST)
    ass(hex(int(i)), "0x10145")
    ass(str(i), "COPY(69, Special.TEST)")
    
    i = POKE(Special.TEST, 69)
    ass(hex(int(i)), "0x20145")
    ass(str(i), "POKE(Special.TEST, 69)")
    i = POKE(Special.TEST, -69)
    ass(hex(int(i)), "0x281bb")
    ass(str(i), "POKE(Special.TEST, -69)")

    i = MODIFY(Mod.COPY, 69)
    ass(hex(int(i)), "0x30145")
    ass(str(i), "MODIFY(Mod.COPY, 69)")

    print("Passed")
