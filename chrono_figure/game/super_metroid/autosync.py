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
NMI_CLOSE = 10
# how far away we aim to move a close NMI
NMI_CLOSE_TARGET = 20
# how we configure Chrono Figure's matchers. see gateware/core.py for what the
# numbers mean
MATCHER_CONFIG = [(0x9583, 2), (0x841c, 1),
    (0x808343, 3), (0x82e526, 3), (0x85813c, 3), (0x82e06b, 3),
    (0x808348, 4), (0x82e52b, 4), (0x858141, 4), (0x82e070, 4)
]

def bound_freq(freq):
    return min(max(freq, 14), 24.75)

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
all_latches = np.insert(all_latches, 35167, [0, 0, 0, 0, 0, 0], axis=0)

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


def do_fix():
    print("fixing problems")
    for gi, group in enumerate(nmi_groups):
        # if the group's frequency is overridden, we have to use it
        override = group.get("override")
        if override is not None:
            if len(group["apu_freqs"]) == len(group["measurements"]) + 1:
                group["apu_freqs"][-1] = bound_freq(override)
            else:
                group["apu_freqs"].append(bound_freq(override))

        # if this group already has a frequency, we can't do anything. this will
        # only happen if the user sets one in the file (or overrode it)
        if len(group["apu_freqs"]) == len(group["measurements"]) + 1:
            continue

        # do we have any information on potential problems?
        if len(group["measurements"]) == 0:
            # nope. try out the default frequency
            group["apu_freqs"].append(default_real)
            continue

        # is there a problem here?
        end_cycle, wait_cycle, num_nmis = group["measurements"][-1]
        ex_end_cycle = group["ex_end_cycle"]
        ex_wait_cycle = group["ex_wait_cycle"]
        busy = (F_CYC-end_cycle+wait_cycle)/F_CYC*100
        closeness = 50-abs(busy-50)

        if group["num_nmis"] != num_nmis:
            problem = "desync"
        elif closeness < NMI_CLOSE and \
                group["apu_accesses"] >= MIN_APU_ACCESSES:
            problem = "too close"
        else:
            # no problem. just reuse the last frequency
            group["apu_freqs"].append(group["apu_freqs"][-1])
            continue

        m = " GROUP {} ".format(gi)
        print(m)
        print("-"*len(m))
        print("problem: ", end="")

        if problem == "desync":
            missed = (wait_cycle-ex_wait_cycle)/F_CYC*100
            print("desync (missed expected time by {:.2f}%)".format(missed))
            if group["apu_accesses"] < MIN_APU_ACCESSES:
                print("but this group does not access the APU. can't help ya "
                    "there, bud")
                # so just reuse the last frequency
                group["apu_freqs"].append(group["apu_freqs"][-1])
                continue
        elif problem == "too close":
            print("got within {:.2f}% of a frame boundary".format(closeness))

        print("curr APU freq: {:.6f}MHz".format(group["apu_freqs"][-1]))

        # calculate expected business if we had a desync as the business above
        # will be nonsense
        if problem == "desync":
            busy = (F_CYC-ex_end_cycle+ex_wait_cycle)/F_CYC*100
            # if it ends sooner than we expect then we need to slow down. once
            # we get it resynced, the other code will handle keeping it away
            # from frame boundaries.
            slow_down = wait_cycle < ex_wait_cycle
        else:
            slow_down = busy < 50 # just not busy enough!
        if busy < 50:
            target = ex_end_cycle - F_CYC*(1-(NMI_CLOSE_TARGET)/100)
        else:
            target = ex_end_cycle - F_CYC*(NMI_CLOSE_TARGET/100)

        if len(group["apu_freqs"]) < 3:
            print("not enough data to predict, so guessing wildly")
            new_freq = group["apu_freqs"][-1]
            delta = random.random()/10
            if slow_down:
                new_freq -= delta
            else:
                new_freq += delta
        else:
            deviations = list(m[1]-ex_end_cycle for m in group["measurements"])
            m, b = np.polyfit(deviations, group["apu_freqs"], 1)
            if abs(m) > 1e-12:
                # if all the apu_freqs are the same (very low m), then corrcoef
                # will whine and spit out a nan
                r = np.corrcoef(deviations, group["apu_freqs"])[0, 1]
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
                new_freq = m*(target-ex_end_cycle) + b
                print("m={}, b={}, new_freq={}".format(m, b, new_freq))

        new_freq = bound_freq(new_freq)
        print("new APU freq: {:.6f}MHz".format(new_freq))
        group["apu_freqs"].append(new_freq) # will be tried next time

        print()


def do_balance_and_build():
    print("balancing cycles")
    # for every cycle we add, we have to remove from somewhere else.
    # hypothetically, this will stop frequency adjustment in one area from
    # affecting the next, because the total number of APU clock cycles will be
    # the same no matter the adjustment.
    surplus = 0 # how many cycles we have to give away
    for gi, group in enumerate(nmi_groups):
        # confirm this group actually got a new frequency
        if len(group["apu_freqs"]) != len(group["measurements"]) + 1:
            raise Exception("group {} didn't get a frequency: {}".format(
                gi, group))

        # calculate the closest frequency we can actually generate
        basic, advanced, actual = calculate_advanced(group["apu_freqs"][-1])
        group["apu_freqs"][-1] = actual
        # since we just clalculated them, update the registers in the TAS too
        latch_start = group["latch_start"]
        if gi > 30330:
            latch_start += 1
        latch_end = group["latch_start"] + group["num_latches"]
        all_latches[latch_start:latch_end, (4, 5)] = (basic, advanced)

        if gi != 30330:
            passed_time = group["latch_clocks"]/(M_FREQ*1e6)
        else:
            passed_time = (group["latch_clocks"]+F_CYC)/(M_FREQ*1e6)
        # how many cycles did we give (with the clock generator) this group?
        curr_freq = actual*1e6
        cycles_given = int(passed_time*curr_freq+0.5)
        # and how many were taken (by the nominal passage of time)?
        cycles_taken = int(passed_time*A_FREQ*1e6+0.5)
        surplus -= cycles_taken

        should_balance = group.get("balance")
        if should_balance is None:
            # if this group accesses the APU, fiddling with the frequency might
            # desync it
            if group["apu_accesses"] >= MIN_APU_ACCESSES:
                should_balance = False
            else:
                should_balance = True

        if not should_balance:
            # just give what we have to give if we can't change it
            surplus += cycles_given
            continue

        # otherwise, can we adjust the frequency of this group to cancel out our
        # surplus?
        if abs(surplus + cycles_given) < 10:
            # avoid bothering with minor issues
            surplus += cycles_given
            continue
        # what frequency would that be?
        desired_freq = bound_freq((-surplus/passed_time)/1e6)
        # what can we actually generate?
        basic, advanced, desired_freq = calculate_advanced(desired_freq)
        new_cycles_given = int(passed_time*desired_freq*1e6+0.5)
        # would this leave us closer to a 0 surplus?
        if abs(surplus + cycles_given) > abs(surplus + new_cycles_given):
            surplus += new_cycles_given # then use it
            group["apu_freqs"][-1] = desired_freq
            all_latches[latch_start:latch_end, (4, 5)] = (basic, advanced)
        else:
            surplus += cycles_given # don't bother

    print("surplus: {} cycles".format(surplus))

mlf = open("mlf.log", "w")
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
    communicate = True # make sure we don't keep communicating once disconnected
    ls.connect(sys.argv[4], status_cb=lambda s: None,
        num_priming_latches=200,
        apu_freq_basic=default_basic,
        apu_freq_advanced=default_advanced,
    )
    # tell it that we are done sending latches (we put the whole tas in already)
    ls.add_latches(None)
    communicate = ls.communicate()

    # start the chrono figure measurement. this will take the console out of
    # reset so we can start reading them after.
    x = input("reset")
    cf.start_measurement()
    print("let go")
    print('measurement setup done')
    nmi_num = 0
    last_end_cycle = 0
    wrap_cycles = 0
    events = []
    finished = False
    desynced = False
    for gi, group in enumerate(nmi_groups):
        group_events = []
        got_event = False
        while True:
            while len(events) == 0 and not finished:
                if communicate: communicate = ls.communicate() # keep tasha full
                events.extend(cf.get_events())
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

        if gi == 30330 and len(group_events) > group["num_nmis"]:
            print("hacking too long")
            group_events.pop()
            last_end_cycle = group_events[-1][0] - wrap_cycles
            wrap_cycles -= F_CYC


        # store the measurement we made
        last = group_events[-1]
        group["measurements"].append([last[0], last[1], len(group_events)])

        if True:
            end_cycle, wait_cycle = group_events[-1]
            busy = (F_CYC-end_cycle+wait_cycle)/F_CYC*100
            ex_end_cycle = group["ex_end_cycle"]
            ex_wait_cycle = group["ex_wait_cycle"]
            ex_busy = (F_CYC-ex_end_cycle+ex_wait_cycle)/F_CYC*100
            m = "{}, {}, {}, {}, {}, {}, {}\n".format(gi, busy, ex_busy,
                end_cycle, wait_cycle, ex_end_cycle, ex_wait_cycle)
            mlf.write(m)

        # if this group doesn't have the same number of NMIs, we must have
        # desynced somehow
        if len(group_events) != group["num_nmis"] and gi >= 21609:
            missed = (group_events[-1][1]-group["ex_wait_cycle"])/F_CYC*100
            print("whoops, group {} desynced (missed expected time by "
                "{:.2f}%).".format(gi, missed), end=" ")
            if group_events[-1][1] >= group["ex_wait_cycle"]:
                print("faster!")
            else:
                print("slower!")
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

    if not desynced: # we finished naturally, make sure the rest works
        print("made it through! finishing TAS...")
        if communicate:
            while ls.communicate(): time.sleep(0.1)
        # wait for the planet to explode to be sure it worked
        time.sleep(20)

    print("measurement run complete")


while True:
    # fix any problems from the last run (or what we just loaded)
    do_fix()
    # balance cycles and create the new TAS
    do_balance_and_build()
    # run it to measure what happens
    do_measure()
    # save what we learned
    print("updating rundata...")
    json.dump(rundata, open(sys.argv[2], "w"), indent=" ")
