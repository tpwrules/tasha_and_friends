# read a log from measure_emulator.lua and write out the run data JSON
# for DKC2 US v1.1

import sys
import json

# convert the pixel counter values to a cycle since reset
# thanks Ilari for the formula
def pixel_to_cycle(f, v, h):
    return f * 357366 - f % 2 * 2 + (v + 21) % 262 * 1364 + h - 386008

out = {}

f = open(sys.argv[1], "r")
if f.readline() != "hello from measure_emulator.lua v1\n":
    raise Exception("invalid greeting")

# get emulated frequencies
freqs = f.readline().split(",")
if freqs[0] != "c":
    raise Exception("invalid frequency format")

nmis = []
latches = []

for line in f:
    bits = tuple(int(b) for b in line.split(",")[1:])
    if line[:2] == "l,":
        latch_cycle = pixel_to_cycle(*bits)
        latches.append(latch_cycle)
    elif line[:2] == "n,":
        nmi = {}
        nmi["wait_cycle"] = pixel_to_cycle(*bits[0:3])
        nmi["end_cycle"] = pixel_to_cycle(*bits[3:6])
        nmi["apu_reads"] = bits[6]
        nmi["apu_writes"] = bits[7]
        nmi["joy_reads"] = bits[8]
        nmi["joy_writes"] = bits[9]
        nmi["door_check"] = bool(bits[10])
        nmi["door_pass"] = bool(bits[11])
        nmi["measurements"] = []

        nmis.append(nmi)
    else:
        raise Exception("invalid record type on line "+line)

# figure out the latch each nmi starts at. it's when we will change the freq
nmi_start_latches = []
latch_num = 0
last_nmi_start = 0
for nmi in nmis:
    num_cycles = nmi["end_cycle"]-last_nmi_start
    last_nmi_start = nmi["end_cycle"]
    # we start at this latch
    nmi_start_latches.append(latch_num)
    # but how many should we go?
    orig_latch_num = latch_num
    while latch_num<len(latches) and latches[latch_num]<(nmi["end_cycle"]-1000):
        latch_num += 1
nmi_start_latches.append(len(latches))

# validate that all nmis start close to their latch (or rather that they end
# close to the next)
for p, z in enumerate(zip(nmis[:-1], nmi_start_latches[:-1])):
    nmi, latch = z
    if abs(latches[nmi_start_latches[p+1]]-nmi["end_cycle"]) > 1000:
        print(nmi, latches[nmi_start_latches[p+1]], nmi["end_cycle"])

# put NMIs into groups. one group is zero or more 100% busy frames followed by a
# not busy frame. these will all be controlled by the same frequency.
nmi_groups = []
these_nmis = []

# if we are currently checking to see if sound effects are done as part of a
# door transition
checking_door = False
# list of some properties of all the doors we've seen
doors = []
# current ID of the door we're checking
curr_door_id = 0

# skip last nmi because i know it's not meaningful and it screws things up
# because we don't have a latch for it
for ni, nmi in enumerate(nmis[:-1]):
    # this nmi is a part of this group
    these_nmis.append(ni)
    if nmi["end_cycle"] == nmi["wait_cycle"]: # is this NMI 100% busy?
        # yup, so there has to be another one in this group
        continue

    door_check = nmis[these_nmis[0]]["door_check"]
    door_pass = nmis[these_nmis[0]]["door_pass"]
    for n in these_nmis[1:]:
        if nmis[n]["door_check"] != door_check or \
                nmis[n]["door_pass"] != door_pass:
            raise Exception("oh no, group is disdoordant")

    first_nmi = these_nmis[0]
    last_nmi = these_nmis[-1]

    apu_accesses = 0
    for gnmi in nmis[first_nmi:last_nmi+1]:
        apu_accesses += (gnmi["apu_reads"]+gnmi["apu_writes"])

    nmi_group = {
        # number of this group (for humans browsing the file). not actually read
        "gid": len(nmi_groups),
        # index of the starting NMI in this group
        "nmi_start": first_nmi,
        # number of NMIs in this group
        "num_nmis": len(these_nmis),
        # latch for the first NMI in this group
        "latch_start": nmi_start_latches[first_nmi],
        # number of latches in this group
        "num_latches":
            nmi_start_latches[last_nmi+1]-nmi_start_latches[first_nmi],
        # how many times this group accesses the APU
        "apu_accesses": apu_accesses,
        # expected end of group from emulator
        "ex_end_cycle": nmis[last_nmi]["end_cycle"],
        # expected start of waiting from emulator
        "ex_wait_cycle": nmis[last_nmi]["wait_cycle"],
        # how many master clock cycles this group's latches took
        "latch_clocks": latches[nmi_start_latches[last_nmi+1]] -\
            latches[nmi_start_latches[first_nmi]],
        # list of APU frequencies applied
        "apu_freqs": [],
        # measurements of each frequency. this is a tuple of (
        #   actual end cycle,
        #   actual start of waiting,
        #   actual number of NMIs,
        # )
        "measurements": [],

        # if len(measurements) == len(apu_freqs), then a new frequency is
        # determined when autosync starts. otherwise, if apu_freqs is 1 longer,
        # that frequency is used instead.

        # optional keys
        # override: if set, always use this APU frequency
        # balance: force inclusion if true (or exclusion if false) in balancing.
        #   if included, then the balancer may edit the frequency.
    }

    if not checking_door and door_check:
        # this is the first group waiting for sound effects to complete
        checking_door = True

        # make a new entry in the door list
        doors.append({})
        # mark a few previous as leading up to the door so we can know to expect
        # it (and have some latitude on changes)
        for pre_door in nmi_groups[-3:]:
            pre_door["door"] = "d"+str(curr_door_id)
            pre_door["door_state"] = "precheck"

    if checking_door:
        # note which door this group belongs to
        nmi_group["door"] = "d"+str(curr_door_id)
        nmi_group["door_state"] = "check"

    if door_pass:
        # the sound effects have completed and next frame we will load the room.
        # this will overwrite the door state above but "pass" implies check too
        nmi_group["door_state"] = "pass"
        checking_door = False
        curr_door_id += 1

    nmi_groups.append(nmi_group)
    these_nmis = []

out["groups"] = nmi_groups

f.close()
f = open(sys.argv[2], "w")
json.dump(out, f, indent=" ")
f.close()
