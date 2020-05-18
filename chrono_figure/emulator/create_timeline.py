# read a log from measure_emulator.lua and write out a timeline JSON

import sys
import json

# convert the pixel counter values to a cycle since reset
# thanks Ilari for the formula
def pixel_to_cycle(f, v, h):
    return f * 357366 - f % 2 * 2 + (v + 21) % 262 * 1364 + h - 386008

out = {}

f = open(sys.argv[1], "r")
if f.readline() != "hello\n":
    raise Exception("invalid greeting")

# get emulated frequencies
freqs = f.readline().split(",")
if not freqs[0].startswith("cpu:") or not freqs[1].startswith("smp"):
    raise Exception("invalid frequency format")

cpu_freq, smp_freq = int(freqs[0][4:]), int(freqs[1][4:])
emu_info = {}
emu_info["cpu_frequency"], emu_info["apu_frequency"] = \
    int(freqs[0][4:]), int(freqs[1][4:])
out["emu_info"] = emu_info

out["runs"] = {} # populated based on measurements from console

header = f.readline()
correct = ("nmi_num,start_latch_num,wait_f,wait_v,wait_h,nmi_f,nmi_v,nmi_h,"
    "apu_r,apu_w,joy_r,joy_w\n")
if header != correct:
    raise Exception("invalid header")

nmis = []

for line in f:
    bits = tuple(int(b) for b in line.split(","))
    nmi = {}
    nmi["start_latch_num"] = bits[1]
    nmi["wait_cycle"] = pixel_to_cycle(*bits[2:5])
    nmi["end_cycle"] = pixel_to_cycle(*bits[5:8])
    nmi["apu_reads"] = bits[8]
    nmi["apu_writes"] = bits[9]
    nmi["joy_reads"] = bits[10]
    nmi["joy_writes"] = bits[11]
    nmi["measurements"] = {}

    nmis.append(nmi)

out["nmis"] = nmis

f.close()
f = open(sys.argv[2], "w")
json.dump(out, f, indent=" ")
f.close()
