# DANGER: NOT TEMPORARY BUT I'M SORRY!

import sys
import time
import json
import random
from collections import namedtuple

import numpy as np

from chrono_figure.host.interface import *
from tasha.host.latch_streamer import LatchStreamer
from tasha.gateware.apu_calc import calculate_advanced

# number of master clock cycles per frame
F_CYC = 357366
# nominal frequency of master clock in MHz. should match the emulator.
M_FREQ = 21.477272
# nominal frequency of APU clock in MHz. should match the emulator.
A_FREQ = 24.607104
# number of APU register accesses needed to consider a group as accessing the
# APU. many games (i.e. dkc2 and smw) access the APU 4 times per frame to play
# sound effects, so we set it higher than that to avoid fiddling with those.
MIN_APU_ACCESSES = 12
# how close (in percent of frame time) an NMI can get to a frame boundary before
# we try to fix it
NMI_CLOSE = 8
# how far away we aim to move a close NMI
NMI_CLOSE_TARGET = 20
# how we configure Chrono Figure's matchers. see gateware/core.py for what the
# numbers mean
MATCHER_CONFIG = [(0xf3bd, 2), (0x83f7, 1), (0x808652, 3), (0x808c9b, 3),
    (0x8097ca, 3), (0x809c96, 3), (0x80ab78, 3), (0x80b106, 3), (0x80b54a, 3),
    (0x80b6be, 3), (0xb5d00e, 3), (0xb5d23c, 3), (0xb5d447, 3)
]

if len(sys.argv) != 5:
    print("args: rundata_in rundata_out r16m tasha_port")
    exit(1)

print("loading...")

rundata = json.load(open(sys.argv[1], "r"))
nmi_groups = rundata["groups"]

def read_all_latches():
    latch_file = open(sys.argv[3], "rb")
    data = latch_file.read()
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    return data[:, (0, 1, 4, 5, 0, 0)].astype(np.uint16)

all_latches = read_all_latches()
# there are a lot of useless latches at the end of the tas. we chop off enough
# that it gets through the first couple seconds of the end credits to confirm
# that the exploit worked before resetting the console
all_latches = all_latches[:21880]

# default (and on-powerup) clock frequency
default_basic, default_advanced, default_real = \
    calculate_advanced(24.607104)
# apply it to the TAS by default to ensure everything has a valid frequency even
# if we never set it
all_latches[:, 4] = default_basic
all_latches[:, 5] = default_advanced

print("chrono figure setup...")
# connect to and set up chrono figure
cf = ChronoFigureInterface()
cf.connect()
# stop saves so our weirdness doesn't screw with the user's saves
cf.prevent_saving(True)
cf.configure_matchers(MATCHER_CONFIG)

ls = LatchStreamer(controllers=["p1d0", "p1d1", "p2d0", "p2d1",
    "apu_freq_basic", "apu_freq_advanced"])

# add starting frequency
for g in nmi_groups:
    g["apu_freqs"].append(default_real)

def do_measure():
    print("starting measurement run...")

    ls.disconnect()
    ls.clear_latch_queue()
    # fill the queue with the TAS
    ls.add_latches(all_latches)

    # hold console in reset while we set up tasha so it doesn't latch anything
    # it shouldn't
    cf.assert_reset(True)
    # erase save memory to ensure a clean start
    cf.destroy_save_ram()
    # connect to tasha to get the tas started
    ls.connect(sys.argv[4], status_cb=lambda s: None,
        num_priming_latches=200,
        apu_freq_basic=default_basic,
        apu_freq_advanced=default_advanced,
    )
    # tell it that we are done sending latches (we put the whole tas in already)
    ls.add_latches(None)
    ls.communicate()

    # start the chrono figure measurement. this will take the console out of
    # reset so we can start reading them after.
    cf.start_measurement()
    print('measurement setup done')
    nmi_num = 0
    last_end_cycle = 0
    wrap_cycles = 0
    measurements = []
    problem_groups = []
    events = []
    finished = False
    desynced = False
    for gi, group in enumerate(nmi_groups):
        group_events = []
        got_event = False
        while True:
            while len(events) == 0 and not finished:
                ls.communicate() # keep tasha full
                try:
                    events.extend(cf.get_events())
                except KeyboardInterrupt:
                    raise
                except:
                    import traceback
                    traceback.print_exc()
                    finished = True

                time.sleep(0.1)

            if len(events) == 0: break

            end_cycle, wait_cycle = events[0]
            events = events[1:]
            if end_cycle < last_end_cycle:
                wrap_cycles += 2**29
            last_end_cycle = end_cycle
            end_cycle += wrap_cycles
            wait_cycle += wrap_cycles
            if end_cycle < wait_cycle:
                wait_cycle -= 2**29

            got_event = True
            group_events.append((end_cycle, wait_cycle))
            if end_cycle != wait_cycle: # not 100% busy, end of group
                break

        if not got_event: break

        # store the measurement we made
        measurements.append(group_events)

        # if this group doesn't have the same number of NMIs, we must have
        # desynced somehow
        if len(group_events) != group["num_nmis"]:
            missed = (group_events[-1][1]-group["ex_wait_cycle"])/F_CYC*100
            print("whoops, group {} desynced (missed expected time by "
                "{:.2f}%).".format(gi, missed), end=" ")
            if group_events[-1][1] >= group["ex_wait_cycle"]:
                print("faster!")
            else:
                print("slower!")
            problem_groups.append(gi)
            desynced = True
            break

        # look at the last nmi in the group
        end_cycle, wait_cycle = group_events[-1]
        busy = (F_CYC-end_cycle+wait_cycle)/F_CYC*100
        closeness = 50-abs(busy-50)
        if closeness < NMI_CLOSE and group["apu_accesses"] >= MIN_APU_ACCESSES:
            print("group {} got within {:.2f}% of boundary & accessed APU "
                "{} times.".format(gi, closeness, group["apu_accesses"]),
                end=" ")
            if busy > 50:
                print("faster!")
            else:
                print("slower!")
            problem_groups.append(gi)

    if not desynced: # we finished naturally, make sure the rest works
        print("made it through! finishing TAS...")
        try:
            while ls.communicate(): time.sleep(0.1)
        except KeyboardInterrupt:
            raise
        except:
            pass

    print("measurement run complete")

    return measurements, problem_groups

num_iters = -1
while True:
    num_iters += 1
    print("building TAS")
    for gi, group in enumerate(nmi_groups):
        # if there isn't a new frequency, use the last one
        if len(group["apu_freqs"]) == len(group["deviations"]):
            group["apu_freqs"].append(group["apu_freqs"][-1])
        # the last frequency was determined last run as the one to try here
        basic, advanced, actual = \
            calculate_advanced(group["apu_freqs"][-1])
        # correct the frequency tried to the one we will actually output
        group["apu_freqs"][-1] = actual
        # apply the register settings to this group's latches
        latch_start = group["latch_start"]
        latch_end = group["latch_start"] + group["num_latches"]
        all_latches[latch_start:latch_end, (4, 5)] = (basic, advanced)

    measurements, problem_groups = do_measure()

    print("updating timeline...")
    for group, measurement in zip(nmi_groups, measurements):
        group["deviations"].append(measurement[-1][1]-group["ex_end_cycle"])

    print("fixing problems")
    for gi in problem_groups:
        print("GROUP {}".format(gi))
        print("------------")
        
        group = nmi_groups[gi]
        measurement = measurements[gi]

        end_cycle, wait_cycle = measurement[-1]
        busy = (F_CYC-end_cycle+wait_cycle)/F_CYC*100
        closeness = 50-abs(busy-50)

        if len(measurement) != group["num_nmis"]:
            missed = (measurement[-1][1]-group["ex_wait_cycle"])/F_CYC*100
            print("problem: desync (missed expected time by {:.2f}%)".format(
                missed))
            if group["apu_accesses"] < MIN_APU_ACCESSES:
                print("but this group does not access the APU. can't help ya "
                    "there, bud")
                continue
        else:
            print("problem: got within {:.2f}% of a frame boundary".format(
                closeness))

        print("curr APU freq: {:.6f}MHz".format(group["apu_freqs"][-1]))

        slow_down = busy < 50 # not busy enough!

        # calculate expected business if we had a desync as the business above
        # will be nonsense
        if len(measurement) != group["num_nmis"]:
            busy = (F_CYC-group["ex_end_cycle"]+
                group["ex_wait_cycle"])/F_CYC*100
            # if it ends sooner than we expect then we need to slow down. once
            # we get it resynced, the other code will handle keeping it away
            # from frame boundaries.
            slow_down = measurement[-1][1] < group["ex_wait_cycle"]
        if busy < 50:
            target = group["ex_end_cycle"] - F_CYC*(1-(NMI_CLOSE_TARGET)/100)
        else:
            target = group["ex_end_cycle"] - F_CYC*(NMI_CLOSE_TARGET/100)

        if len(group["apu_freqs"]) < 3:
            print("not enough data to predict, so guessing wildly")
            new_freq = group["apu_freqs"][-1]
            delta = random.random()/10
            if slow_down:
                new_freq -= delta
            else:
                new_freq += delta
        else:
            m, b = np.polyfit(group["deviations"], group["apu_freqs"], 1)
            if abs(m) > 1e-13:
                # if all the apu_freqs are the same (very low m), then corrcoef
                # will whine and spit out a nan
                r = np.corrcoef(group["deviations"], group["apu_freqs"])[0, 1]
            else:
                r = None
            if r is None or (r**2) < 0.5: # avoid trying to predict on bad data
                print("prediction failed, guessing wildly")
                new_freq = group["apu_freqs"][-1]
                delta = random.random()/10
                if slow_down:
                    new_freq -= delta
                else:
                    new_freq += delta
            else:
                print("predicting based on linear fit with "
                    "R^2={:.3f}".format(r**2))
                new_freq = m*(target-group["ex_end_cycle"]) + b
                print("m={}, b={}, new_freq={}".format(m, b, new_freq))

        new_freq = min(max(new_freq, 23), 24.75)
        print("new APU freq: {:.6f}MHz".format(new_freq))
        group["apu_freqs"].append(new_freq) # will be tried next time

        print()

    print("balancing cycles")
    # for every cycle we add, we have to remove from somewhere else.
    # hypothetically, this will stop frequency adjustment in one area from
    # affecting the next, because the total number of APU clock cycles will be
    # the same no matter the adjustment.
    surplus = 0 # how many cycles we have to give away
    for gi, group in enumerate(nmi_groups):
        latch_start = group["latch_start"]
        latch_end = group["latch_start"] + group["num_latches"]
        # how many cycles did we give (with the clock generator) this group?
        passed_time = group["latch_clocks"]/(M_FREQ*1e6)
        curr_freq = group["apu_freqs"][-1]*1e6
        cycles_given = int(passed_time*curr_freq+0.5)
        # and how many were taken (by the nominal passage of time)?
        cycles_taken = int(passed_time*A_FREQ*1e6+0.5)
        surplus -= cycles_taken

        # if this group accesses the APU, fiddling with the frequency might
        # desync it
        if group["apu_accesses"] >= MIN_APU_ACCESSES:
            # so we just give what we have to give to stop that
            surplus += cycles_given
            continue

        # otherwise, can we adjust the frequency of this group to cancel out our
        # surplus?
        if abs(surplus + cycles_given) < 10:
            # avoid bothering with minor issues
            surplus += cycles_given
            continue
        # what frequency would that be?
        desired_freq = (-surplus/passed_time)/1e6
        desired_freq = min(max(desired_freq, 23), 24.75)
        # what can we actually generate
        _, _, desired_freq = calculate_advanced(desired_freq)
        new_cycles_given = int(passed_time*desired_freq*1e6+0.5)
        # would this leave us closer to a 0 surplus?
        if abs(surplus + cycles_given) > abs(surplus + new_cycles_given):
            surplus += new_cycles_given # then use it
            group["apu_freqs"].append(desired_freq)
        else:
            surplus += cycles_given # don't bother

    print("surplus: {} cycles".format(surplus))
