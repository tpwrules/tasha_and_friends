# DANGER: EXCESSIVELY TEMPORARY CODE!

import sys
import time
import json
import random

import numpy as np

from .interface import ChronoFigureInterface
from tasha.host.latch_streamer import LatchStreamer
from tasha.gateware.apu_calc import calculate_advanced

F_CYC = 357366 # number of clock cycles per frame

if len(sys.argv) != 5:
    print("args: timeline_in timeline_out r16m tasha_port")
    exit(1)

print("loading")

timeline = json.load(open(sys.argv[1], "r"))
t_nmis = timeline["nmis"]

def read_all_latches():
    latch_file = open(sys.argv[3], "rb")
    data = latch_file.read()
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    return data[:, (0, 1, 4, 5, 0, 0)].astype(np.uint16)

all_latches = read_all_latches()

# fill with default clock frequency
default_basic, default_advanced, default_real = calculate_advanced(24.607104)
freqs = [default_real]*len(all_latches)
all_latches[:, 4] = default_basic
all_latches[:, 5] = default_advanced

# figure out what latch each nmi starts at. this is when we will change the freq
nmi_start_latches = []
latch_num = 0
last_nmi_start = 0
t_ls = timeline["latches"]
for nmi in t_nmis:
    num_cycles = nmi["end_cycle"]-last_nmi_start
    last_nmi_start = nmi["end_cycle"]
    # we start at this latch
    nmi_start_latches.append(latch_num)
    # but how many should we go?
    orig_latch_num = latch_num
    while latch_num < len(t_ls) and t_ls[latch_num] < (nmi["end_cycle"] - 1000):
        latch_num += 1
    if orig_latch_num == latch_num:
        raise Exception("oop!")

# validate that all nmis start close to their latch (or rather that they end
# close to the next)
for nmi, latch in zip(t_nmis[:-1], nmi_start_latches[:-1]):
    p = nmi_start_latches.index(latch)
    if abs(t_ls[nmi_start_latches[p+1]]-nmi["end_cycle"]) > 1000:
        print(nmi, t_ls[nmi_start_latches[p+1]], nmi["end_cycle"])

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
    ls.connect(sys.argv[4], status_cb=lambda s: 0,
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
    last_nmi_cycle = 0
    wrap_cycles = 0
    measurements = []
    problem_nmis = []
    while True:
        ls.communicate() # keep tasha full

        try:
            events = cf.get_events()
        except:
            import traceback
            traceback.print_exc()
            break
        desync = False
        for event, nmi in zip(events, t_nmis[nmi_num:nmi_num+len(events)]):
            nmi_cycle, wait_cycle = event
            if nmi_cycle < last_nmi_cycle:
                wrap_cycles += 2**29
            last_nmi_cycle = nmi_cycle
            nmi_cycle += wrap_cycles
            wait_cycle += wrap_cycles
            if nmi_cycle < wait_cycle:
                wait_cycle -= 2**29

            # expected from the emulator
            ex_nmi_cycle, ex_wait_cycle = nmi["end_cycle"], nmi["wait_cycle"]
            apu_tot = nmi["apu_reads"] + nmi["apu_writes"]

            busy = (F_CYC-nmi_cycle+wait_cycle)/F_CYC*100
            ex_busy = (F_CYC-ex_nmi_cycle+ex_wait_cycle)/F_CYC*100

            measurements.append((nmi_cycle, wait_cycle))

            do_print = False
            a_problem = False
            desync = False
            if abs(ex_nmi_cycle-nmi_cycle) > 1000:
                print("big nmi diff:", end=" ")
                do_print = True
                a_problem = True
                desync = True

            if (busy > 99.99 and ex_busy <= 99.99) or \
                    (ex_busy > 99.99 and busy <= 99.99):
                print("busy desync:", end=" ")
                do_print = True
                a_problem = True
                desync = True

            # if abs(busy-ex_busy) > 1:
            #     print("big busy diff:", end=" ")
            #     do_print = True

            if abs(busy-50) > 40 and apu_tot > 4 and busy < 99.999:
                print("got close:", end=" ")
                do_print = True
                a_problem = True

            if abs(ex_busy-50) > 40 and apu_tot > 4 and busy < 99.999:
                print("should be close:", end=" ")
                do_print = True

            if a_problem:
                problem_nmis.append(nmi_num)

            if do_print:
                print("nmi:{} busy:{:.2f}% ex_busy:{:.2f}% "
                    "nmi_cycle:{} ex_nmi_cycle:{} apu_tot:{}".format(
                    nmi_num, busy, ex_busy, nmi_cycle, ex_nmi_cycle, apu_tot))

            if desync:
                print("desynchrolized!!")
                break

            nmi_num += 1

        if desync:
            break

        time.sleep(0.1)

    print("measurement run complete")

    return measurements, problem_nmis

acs_template = {
    "source": "TASHA",
    "actual": 24.607104,
    "jitter": 0,
    "jitter_mode": False,
    "polarity": False,
    "applied": 0,
}
import pickle
while True:
    measurements, problem_nmis = do_measure()
    pickle.dump((freqs, measurements, problem_nmis), open("bak.pickle", "wb"))
    print("updating timeline...")

    rid = len(timeline["runs"])
    run = {"name": "hello", "apu_clock_source": acs_template.copy()}
    timeline["runs"].append(run)
    for mi, m in enumerate(measurements):
        acs = acs_template.copy()
        acs["applied"] = t_ls[nmi_start_latches[mi]]
        acs["actual"] = freqs[nmi_start_latches[mi]]
        measurement = {
            "rid": rid,
            "wait_cycle": m[1],
            "end_cycle": m[0],
            "apu_clock_source": acs,
        }
        t_nmis[mi]["measurements"].append(measurement)

    json.dump(timeline, open(sys.argv[2], "w"), indent=" ")

    print("fixing problems")
    for pi in problem_nmis:
        print("NMI {}".format(pi))
        print("------------")
        nmi = t_nmis[pi]

        nmi_cycle, wait_cycle = measurements[pi]

        # expected from the emulator
        ex_nmi_cycle, ex_wait_cycle = nmi["end_cycle"], nmi["wait_cycle"]
        apu_tot = nmi["apu_reads"] + nmi["apu_writes"]

        busy = (F_CYC-nmi_cycle+wait_cycle)/F_CYC*100
        ex_busy = (F_CYC-ex_nmi_cycle+ex_wait_cycle)/F_CYC*100

        if abs(ex_nmi_cycle-nmi_cycle) > 1000:
            print("problem: desync")
            if apu_tot < 4:
                print("but this NMI does not access the APU. can't help ya "
                    "there, bud")
                continue
        else:
            print("problem: got within {:.2f}% of a frame boundary "
                "(less than 10%)".format(50-abs(busy-50)))

        print("curr APU freq: {:.6f}MHz".format(freqs[nmi_start_latches[pi]]))

        if busy < 50: # bump to 20%
            target = ex_nmi_cycle - F_CYC*.8
        else: # bump to 80%
            target = ex_nmi_cycle - F_CYC*.2

        # figure out APU frequency vs. cycle deviation (from end of nmi)
        deviations = []
        for m in nmi["measurements"]:
            deviations.append((m["wait_cycle"]-ex_nmi_cycle,
                m["apu_clock_source"]["actual"]))
        deviations = np.asarray(deviations)

        if len(deviations) < 6:
            print("not enough data to predict, so guessing wildly")
            new_freq = freqs[nmi_start_latches[pi]]
            delta = random.random()/10
            if new_freq > 24.64:
                new_freq -= delta
            else:
                new_freq += delta
        else:
            m, b = np.polyfit(deviations[:, 0], deviations[:, 1], 1)
            r = np.corrcoef(deviations[:, 0], deviations[:, 1])[0, 1]
            if r != r: # true if r is NaN
                print("prediction failed, guessing wildly")
                new_freq = freqs[nmi_start_latches[pi]]
                delta = random.random()/10
                if new_freq > 24.64:
                    new_freq -= delta
                else:
                    new_freq += delta
            else:
                print("predicting based on linear fit with "
                    "R^2={:.3f}".format(r**2))
                new_freq = m*(target-ex_nmi_cycle) + b
                print("m={}, b={}, new_freq={}".format(m, b, new_freq))

        new_freq = min(max(new_freq, 23), 24.75)
        basic, advanced, actual = calculate_advanced(new_freq)
        print("new APU freq: {:.6f}MHz".format(new_freq))

        for li in range(nmi_start_latches[pi], nmi_start_latches[pi+1]):
            freqs[li] = actual
            all_latches[li, 4] = basic
            all_latches[li, 5] = advanced

        print()
