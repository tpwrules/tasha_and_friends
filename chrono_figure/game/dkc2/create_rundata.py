# read a log from measure_emulator.lua and write out a timeline JSON

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

emu_info = {}
emu_info["cpu_frequency"] = int(freqs[1])
emu_info["smp_frequency"] = int(freqs[2])
out["emu_info"] = emu_info

out["runs"] = [] # populated based on measurements from console

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



out["nmis"] = nmis
out["latches"] = latches

f.close()
f = open(sys.argv[2], "w")
json.dump(out, f, indent=" ")
f.close()
