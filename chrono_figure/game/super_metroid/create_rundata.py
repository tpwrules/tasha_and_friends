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
for ni, nmi in enumerate(nmis):
    # this nmi is a part of this group
    these_nmis.append(ni)
    if nmi["end_cycle"] == nmi["wait_cycle"]: # is this NMI 100% busy?
        # yup, so there has to be another one in this group
        continue

    first_nmi = these_nmis[0]
    last_nmi = these_nmis[-1]

    apu_accesses = 0
    for gnmi in nmis[first_nmi:last_nmi+1]:
        apu_accesses += (gnmi["apu_reads"]+gnmi["apu_writes"])

    nmi_groups.append({
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
    })

    these_nmis = []

out["groups"] = nmi_groups

f.close()
f = open(sys.argv[2], "w")
json.dump(out, f, indent=" ")
f.close()
