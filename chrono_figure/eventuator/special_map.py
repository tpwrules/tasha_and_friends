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