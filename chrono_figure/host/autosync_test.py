# DANGER: EXCESSIVELY TEMPORARY CODE!

import sys
import time
import json
import random
from collections import namedtuple

import numpy as np

from .interface import ChronoFigureInterface
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
MIN_APU_ACCESSES = 5
# how close (in percent of frame time) an NMI can get to a frame boundary before
# we try to fix it
NMI_CLOSE = 10
# how far away we aim to move a close NMI
NMI_CLOSE_TARGET = 20

if len(sys.argv) != 5:
    print("args: timeline_in timeline_out r16m tasha_port")
    exit(1)

print("loading...")

timeline = json.load(open(sys.argv[1], "r"))
t_nmis = timeline["nmis"]
t_ls = timeline["latches"]

def read_all_latches():
    latch_file = open(sys.argv[3], "rb")
    data = latch_file.read()
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    return data[:, (0, 1, 4, 5, 0, 0)].astype(np.uint16)

all_latches = read_all_latches()

# remove blank trailing latches
nr = 0
for r in all_latches[::-1]:
    if np.any(r != 0):
        break
    nr += 1
nr -= 600
if nr > 0:
    all_latches = all_latches[:-nr]

# default (and on-powerup) clock frequency
default_basic, default_advanced, default_real = \
    calculate_advanced(24.607104)

# hold one group of NMIs that theoretically are related and whose APU frequency
# will be controlled as one. one group consists of a set of contiguous NMIs with
# the first zero or more being 100% busy and the last being not 100% busy. this
# should comprise one frame of game logic.
NMIGroup = namedtuple("NMIGroup", [
    "nmi_start", # index of the starting NMI in this group
    "num_nmis", # number of NMIs in the group
    "latch_start", # latch for the first NMI in the group
    "num_latches", # how many latches in the group
    "apu_accesses", # how many times this group accesses the APU
    "ex_end_cycle", # expected values from the emulator
    "ex_wait_cycle",
    "apu_freqs", # list of APU frequencies applied
    "deviations", # deviations (measured_wait-ex_end_cycle) for each frequency
])

def group():
    # figure out the latch each nmi starts at. it's when we will change the freq
    nmi_start_latches = []
    latch_num = 0
    last_nmi_start = 0
    for nmi in t_nmis:
        num_cycles = nmi["end_cycle"]-last_nmi_start
        last_nmi_start = nmi["end_cycle"]
        # we start at this latch
        nmi_start_latches.append(latch_num)
        # but how many should we go?
        orig_latch_num = latch_num
        while latch_num<len(t_ls) and t_ls[latch_num]<(nmi["end_cycle"] - 1000):
            latch_num += 1
        if orig_latch_num == latch_num:
            raise Exception("oop!")
    nmi_start_latches.append(len(t_ls))

    # validate that all nmis start close to their latch (or rather that they end
    # close to the next)
    for nmi, latch in zip(t_nmis[:-1], nmi_start_latches[:-1]):
        p = nmi_start_latches.index(latch)
        if abs(t_ls[nmi_start_latches[p+1]]-nmi["end_cycle"]) > 1000:
            print(nmi, t_ls[nmi_start_latches[p+1]], nmi["end_cycle"])

    nmi_groups = []
    these_nmis = []
    for ni, nmi in enumerate(t_nmis):
        # this nmi is a part of this group
        these_nmis.append(ni)
        if nmi["end_cycle"] == nmi["wait_cycle"]: # is this NMI 100% busy?
            # yup, so there has to be another one in this group
            continue

        first_nmi = these_nmis[0]
        last_nmi = these_nmis[-1]

        apu_accesses = 0
        for gnmi in t_nmis[first_nmi:last_nmi+1]:
            apu_accesses += (gnmi["apu_reads"]+gnmi["apu_writes"])

        this_group = NMIGroup(
            nmi_start=first_nmi,
            num_nmis=len(these_nmis),
            latch_start=nmi_start_latches[first_nmi],
            num_latches=\
                nmi_start_latches[last_nmi+1]-nmi_start_latches[first_nmi],
            apu_accesses=apu_accesses,
            ex_end_cycle=t_nmis[last_nmi]["end_cycle"],
            ex_wait_cycle=t_nmis[last_nmi]["wait_cycle"],
            apu_freqs=[default_real],
            deviations=[],
        )

        nmi_groups.append(this_group)
        these_nmis = []

    return nmi_groups
nmi_groups = group()

print("chrono figure setup...")
# connect to and set up chrono figure
cf = ChronoFigureInterface()
cf.connect()
# stop saves so our weirdness doesn't screw with the user's saves
cf.prevent_saving(True)
# configure the matchers on dkc2's addresses (from game_addrs/dkc2.txt)
cf.configure_matchers([(0xf3bd, 2), (0x83f7, 1), (0x808652, 3), (0x808c9b, 3),
    (0x8097ca, 3), (0x809c96, 3), (0x80ab78, 3), (0x80b106, 3), (0x80b54a, 3),
    (0x80b6be, 3), (0xb5d00e, 3), (0xb5d23c, 3), (0xb5d447, 3)])

ls = LatchStreamer(controllers=["p1d0", "p1d1", "p2d0", "p2d1",
    "apu_freq_basic", "apu_freq_advanced"])

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
        if len(group_events) != group.num_nmis:
            missed = (group_events[-1][1]-group.ex_wait_cycle)/F_CYC*100
            print("whoops, group {} desynced (missed expected time by "
                "{:.2f}%).".format(gi, missed), end=" ")
            if group_events[-1][1] >= group.ex_wait_cycle:
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
        if closeness < NMI_CLOSE and group.apu_accesses >= MIN_APU_ACCESSES:
            print("group {} got within {:.2f}% of boundary & accessed APU "
                "{} times.".format(gi, closeness, group.apu_accesses), end=" ")
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
        if len(group.apu_freqs) == len(group.deviations):
            group.apu_freqs.append(group.apu_freqs[-1])
        # the last frequency was determined last run as the one to try here
        basic, advanced, actual = \
            calculate_advanced(group.apu_freqs[-1])
        # correct the frequency tried to the one we will actually output
        group.apu_freqs[-1] = actual
        # apply the register settings to this group's latches
        latch_start = group.latch_start
        latch_end = group.latch_start + group.num_latches
        all_latches[latch_start:latch_end, (4, 5)] = (basic, advanced)

    measurements, problem_groups = do_measure()

    print("updating timeline...")
    for group, measurement in zip(nmi_groups, measurements):
        group.deviations.append(measurement[-1][1]-group.ex_end_cycle)

    print("fixing problems")
    for gi in problem_groups:
        print("GROUP {}".format(gi))
        print("------------")
        
        group = nmi_groups[gi]
        measurement = measurements[gi]

        end_cycle, wait_cycle = measurement[-1]
        busy = (F_CYC-end_cycle+wait_cycle)/F_CYC*100
        closeness = 50-abs(busy-50)

        if len(measurement) != group.num_nmis:
            missed = (measurement[-1][1]-group.ex_wait_cycle)/F_CYC*100
            print("problem: desync (missed expected time by {:.2f}%)".format(
                missed))
            if group.apu_accesses < MIN_APU_ACCESSES:
                print("but this group does not access the APU. can't help ya "
                    "there, bud")
                continue
        else:
            print("problem: got within {:.2f}% of a frame boundary".format(
                closeness))

        print("curr APU freq: {:.6f}MHz".format(group.apu_freqs[-1]))

        # calculate expected business if we had a desync as the business above
        # will be nonsense
        if len(measurement) != group.num_nmis:
            busy = (F_CYC-group.ex_end_cycle+group.ex_wait_cycle)/F_CYC*100
        if busy < 50:
            target = group.ex_end_cycle - F_CYC*(1-(NMI_CLOSE_TARGET)/100)
        else:
            target = group.ex_end_cycle - F_CYC*(NMI_CLOSE_TARGET/100)

        if len(group.apu_freqs) < 3:
            print("not enough data to predict, so guessing wildly")
            new_freq = group.apu_freqs[-1]
            delta = random.random()/10
            if busy < 50: # need to slow down and be more busy
                new_freq -= delta
            else:
                new_freq += delta
        else:
            m, b = np.polyfit(group.deviations, group.apu_freqs, 1)
            if abs(m) > 1e-13:
                # if all the apu_freqs are the same (very low m), then corrcoef
                # will whine and spit out a nan
                r = np.corrcoef(group.deviations, group.apu_freqs)[0, 1]
            else:
                r = None
            if r is None or (r**2) < 0.5: # avoid trying to predict on bad data
                print("prediction failed, guessing wildly")
                new_freq = group.apu_freqs[-1]
                delta = random.random()/10
                if busy < 50: # need to slow down and be more busy
                    new_freq -= delta
                else:
                    new_freq += delta
            else:
                print("predicting based on linear fit with "
                    "R^2={:.3f}".format(r**2))
                new_freq = m*(target-group.ex_end_cycle) + b
                print("m={}, b={}, new_freq={}".format(m, b, new_freq))

        new_freq = min(max(new_freq, 23), 24.75)
        print("new APU freq: {:.6f}MHz".format(new_freq))
        group.apu_freqs.append(new_freq) # will be tried next time

        print()

    import pickle
    pickle.dump(nmi_groups, 
        open("autosync_nmi_cycles_{}.pickle".format(num_iters), "wb"))

    print("balancing cycles")
    # for every cycle we add, we have to remove from somewhere else.
    # hypothetically, this will stop frequency adjustment in one area from
    # affecting the next, because the total number of APU clock cycles will be
    # the same no matter the adjustment.
    surplus = 0 # how many cycles we have to give away
    for gi, group in enumerate(nmi_groups):
        latch_start = group.latch_start
        latch_end = group.latch_start + group.num_latches
        # how many cycles did we give (with the clock generator) this group?
        passed_time = (t_ls[latch_end] - t_ls[latch_start])/(M_FREQ*1e6)
        curr_freq = group.apu_freqs[-1]*1e6
        cycles_given = int(passed_time*curr_freq+0.5)
        # and how many were taken (by the nominal passage of time)?
        cycles_taken = int(passed_time*A_FREQ*1e6+0.5)
        surplus -= cycles_taken

        # if this group accesses the APU, fiddling with the frequency might
        # desync it
        if group.apu_accesses >= MIN_APU_ACCESSES:
            # so we just give what we have to give to stop that
            surplus += cycles_given
            continue

        # otherwise, can we adjust the frequency of this group to cancel out our
        # surplus?
        if abs(surplus + cycles_given) < 1000:
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
            group.apu_freqs.append(desired_freq)
        else:
            surplus += cycles_given # don't bother

    print("surplus: {} cycles".format(surplus))
