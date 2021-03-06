# this file contains the memory map of the special registers and automatically
# builds all the addressing data

# each entry contains the width of the unit's address bus. there is also the
# definitions of all the registers, including their full name and offset from
# the base. the base of each entry is automatically calculated. the width of
# each unit's address bus is widened as much as possible to reduce decoding
# logic.

from enum import IntEnum

SPL_WIDTH = 7

special_map = {
    "spl_temp": {
        "width": 1,
        "regs": (
            ("TMPA", 0, "rw"),
            ("TMPB", 1, "rw"),
        ),
    },

    "spl_imm": {
        "width": 2,
        "regs": (
            ("IMM_B0", 0, "w"),
            ("IMM_B1", 1, "w"),
            ("IMM_B2", 2, "w"),
            ("IMM_B3", 3, "w"),
            ("IMM_VAL", 0, "r"),
        ),
    },

    "spl_alu_frontend": {
        "width": 2,
        "regs": (
            ("ALU_B0", 0, "w"),
            ("ALU_B1", 1, "w"),
            ("ALU_FLAGS", 2, "rw"),
        ),
    },

    "spl_event_fifo": {
        "width": 0,
        "regs": (
            ("EVENT_FIFO", 0, "w"),
        ),
    },

    "spl_match_config": {
        "width": 1,
        "regs": (
            ("MATCH_CONFIG_ADDR", 0, "w"),
            ("MATCH_CONFIG_DATA", 1, "w"),
        ),
    },

    "spl_match_info": {
        "width": 2,
        "regs": (
            ("MATCH_TYPE", 0, "r"),
            ("MATCH_CYCLE_COUNT", 1, "r"),
            ("MATCH_ADDR", 2, "r"),
            ("MATCH_DATA", 3, "r"),
            ("MATCH_ENABLE", 0, "w"),
        ),
    },

    "spl_mod_offset": {
        "width": 2,
        "regs": (
            ("MOFF_RD_TEMP", 0, "w"),
            ("MOFF_WR_TEMP", 1, "w"),
            ("MOFF_RD_HOLD", 2, "w"),
            ("MOFF_WR_HOLD", 3, "w"),
        )
    },

    "spl_branch_ind": {
        "width": 0,
        "regs": (
            ("BRANCH_IND_TARGET", 0, "w"),
            ("CURR_PC", 0, "r"),
        ),
    },

    "spl_match_timer": {
        "width": 2,
        "regs": (
            ("MTIM0_VAL", 0, "r"),
            ("MTIM0_CTL", 0, "w"),
            ("MTIM1_VAL", 1, "r"),
            ("MTIM1_CTL", 1, "w"),
            ("MTIM2_VAL", 2, "r"),
            ("MTIM2_CTL", 2, "w"),
        )
    }
}

# validate the units and calculate the base addresses
def _map():
    units = []
    remaining_addrs = 2**SPL_WIDTH
    for name, unit in special_map.items():
        count = 2**unit["width"]
        remaining_addrs -= count
        if remaining_addrs < 0:
            raise Exception("unit {} cannot fit".format(name))
        for reg, offset, access in unit["regs"]:
            if offset >= count:
                raise Exception("register {} cannot fit in unit {}".format(
                    reg, name))

        units.append([unit["width"], name])

    # attempt to widen address buses. this reduces decoding logic by introducing
    # address bits that don't matter.
    while True:
        # we need to allocate the widest buses first and we want to widen the
        # narrowest. sort by width, then by name for determinism.
        units.sort(reverse=True)
        reqd = 2**units[-1][0] # how many addresses would it take to widen?
        if reqd > remaining_addrs: break # too many, we can't widen any more
        remaining_addrs -= reqd
        units[-1][0] += 1

    # hand out base addresses to everybody
    base = 0
    for width, name in units:
        special_map[name]["width"] = width
        special_map[name]["base"] = base
        base += 2**width

_map()
del _map

# generate the register number enums
def _generate():
    r_regs = []
    w_regs = []

    for name, unit in special_map.items():
        base = unit["base"]
        for reg, offset, access in unit["regs"]:
            enum_members = ((reg, base+offset), (reg+"_OFFSET", offset))
            if "r" in access: r_regs.extend(enum_members)
            if "w" in access: w_regs.extend(enum_members)

    return IntEnum('SplR', r_regs), IntEnum('SplW', w_regs)

SplR, SplW = _generate()
del _generate
