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
    EQ = Z1 = Z  = 8
    NE = Z0 = NZ = 9
    # S = 1
    MI = S1 = 10
    PL = S0 = 11
    # C = 1
    CS = GEU = C1 = 12
    CC = LTU = C0 = 13
    # V = 1
    VS = V1 = 14
    VC = V0 = 15

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


class Insn:
    def _assemble(self, flag, special, reg):
        if not isinstance(reg, int):
            raise ValueError("reg is {}, not int".format(type(reg)))
        if reg < 0 or reg >= 2**REGS_WIDTH:
            raise ValueError("reg {} is out of range".format(reg))
        return ((int(self.code) << 16) +
            (int(flag) << 15) +
            (int(special) << 8) +
            (reg))

# set the PC to the destination if the condition is true
class BRANCH(Insn):
    def __init__(self, dest, cond=Cond.ALWAYS):
        self.code = InsnCode.BRANCH
        self.dest = dest

        if not isinstance(cond, Cond):
            raise ValueError("invalid condition")
        self.cond = cond

    def __int__(self):
        if not isinstance(self.dest, int):
            raise ValueError("dest is {}, not int".format(type(self.dest)))
        if self.dest < 0 or self.dest >= 2**PC_WIDTH:
            raise ValueError("dest pc {} is out of range".format(self.dest))

        return ((int(self.code) << 16) + (int(self.cond) << 12) + self.dest)

    def __repr__(self):
        return "BRANCH({!r}, {})".format(self.dest, str(self.cond))

# copy a special register to a regular register or vice versa
class COPY(Insn):
    def __init__(self, dest, src):
        self.code = InsnCode.COPY
        if isinstance(dest, SplR):
            raise ValueError("can't write to SplR")
        if isinstance(src, SplW):
            raise ValueError("can't read from SplW")
        if isinstance(dest, SplW) and isinstance(src, SplR):
            raise ValueError("can't copy special to special")
        if not isinstance(dest, SplW) and not isinstance(src, SplR):
            raise ValueError("can't copy reg to reg")

        if isinstance(dest, SplW):
            self.dest_special = True
            self.special = dest
            self.reg = src
        else:
            self.dest_special = False
            self.special = src
            self.reg = dest

    def __int__(self):
        return self._assemble(self.dest_special, self.special, self.reg)

    def __repr__(self):
        if self.dest_special:
            return "COPY({}, {!r})".format(str(self.special), self.reg)
        else:
            return "COPY({!r}, {})".format(self.reg, str(self.special))

# write a 9-bit sign-extended value to a special register
class POKE(Insn):
    def __init__(self, special, val):
        self.code = InsnCode.POKE
        if not isinstance(special, SplW):
            raise ValueError("can only poke SplW")
        self.special = special

        self.val = val

    def __int__(self):
        if not isinstance(self.val, int):
            raise ValueError("val is {}, not int".format(type(self.val)))
        if self.val < -256 or self.val > 511:
            raise ValueError("val {} is out of range".format(self.val))

        return self._assemble((self.val>>8) & 1, self.special, self.val & 0xFF)

    def __repr__(self):
        return "POKE({}, {!r})".format(str(self.special), self.val)

# do a read-modify-write operation on a register
class MODIFY(Insn):
    def __init__(self, reg, mod):
        self.code = InsnCode.MODIFY
        if not isinstance(mod, Mod):
            raise ValueError("not a valid Mod")
        self.mod = mod

        self.reg = reg

    def __int__(self):
        mod = int(self.mod)
        return self._assemble(mod >> 7, mod & 0x7F, self.reg)

    def __repr__(self):
        return "MODIFY({!r}, {})".format(self.reg, str(self.mod))

# define a label for the assembler
class L(Insn):
    def __init__(self, label, org=None):
        if not isinstance(label, str) or len(label) == 0:
            raise ValueError("invalid label string")
        if org is not None and (org < 0 or org >= 2**PC_WIDTH):
            raise ValueError("location {} is out of range".format(org))
        self.location = org
        self.label = label
        self.local = label[0] == "_" # can be reused after a non-local

    def __repr__(self):
        if self.location is None:
            return "L({!r})".format(self.label)
        else:
            return "L({!r}, org={})".format(self.label, self.location)

def ev_assemble(program_in, start_pc=1, return_labels=False):
    if start_pc < 1 or start_pc >= 2**PC_WIDTH:
        raise ValueError("start PC {} is out of range".format(start_pc))

    pc = start_pc
    last_nonlocal = ""
    labels = {}
    program = []
    # find all the labels, assign their addresses, and copy the instructions to
    # their final location
    for instruction in program_in:
        if not isinstance(instruction, Insn):
            raise ValueError(
                "pc={}: {!r} is not an Insn".format(instruction, pc))
        # copy all the instructions so we can change the labels in them later
        if isinstance(instruction, BRANCH):
            b = BRANCH(instruction.dest, instruction.cond)
            # delocalize local labels by appending the last non-local label
            if isinstance(b.dest, str) and b.dest[0] == "_":
                b.dest = "{}@{}".format(b.dest, last_nonlocal)
            program.append(b)
        elif isinstance(instruction, COPY):
            if instruction.dest_special:
                program.append(COPY(instruction.special, instruction.reg))
            else:
                program.append(COPY(instruction.reg, instruction.special))
        elif isinstance(instruction, POKE):
            program.append(POKE(instruction.special, instruction.val))
        elif isinstance(instruction, MODIFY):
            program.append(MODIFY(instruction.reg, instruction.mod))
        else: # must be a label
            l = L(instruction.label, org=instruction.location)
            if not l.local:
                last_nonlocal = l.label
            else: # delocalize the local label
                l.label = "{}@{}".format(l.label, last_nonlocal)
            if l.location is None: # set its location if not already given
                l.location = pc
            if l.location < pc:
                raise ValueError("pc={}: {} is before pc".format(pc, str(l)))
            program.extend([BRANCH(0)]*(l.location-pc))
            pc = l.location
            labels[l.label] = l.location
        if not isinstance(instruction, L):
            pc += 1

    assembled_program = []
    # replace labels in branches and assemble the program
    for instruction in program:
        if isinstance(instruction, BRANCH) and isinstance(instruction.dest, str):
            try:
                instruction.dest = labels[instruction.dest]
            except KeyError:
                raise ValueError("pc={}: unknown label {!r}".format(
                    start_pc+len(assembled_program), instruction.dest))
        try:
            assembled_program.append(int(instruction))
        except Exception as e:
            raise ValueError("pc={}: {} assembly error: {}".format(
                start_pc+len(assembled_program), str(instruction),
                    str(e))) from e

    if not return_labels:
        return assembled_program
    else:
        return assembled_program, labels
