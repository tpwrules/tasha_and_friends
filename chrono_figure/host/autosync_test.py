# DANGER: EXCESSIVELY TEMPORARY CODE!

import sys
import time
import json

import numpy as np

from .interface import ChronoFigureInterface
from tasha.host.latch_streamer import LatchStreamer
from tasha.gateware.apu_calc import calculate_advanced

F_CYC = 357366 # number of clock cycles per frame

if len(sys.argv) != 5:
    print("args: timeline_in timeline_out r16m tasha_port")
    exit(1)

timeline = json.load(open(sys.argv[1], "r"))
t_nmis = timeline["nmis"]

def read_all_latches():
    latch_file = open(sys.argv[3], "rb")
    data = latch_file.read()
    data = np.frombuffer(data, dtype='>u2').reshape(-1, 8)
    return data[:, (0, 1, 4, 5, 0, 0)].astype(np.uint16)

all_latches = read_all_latches()

# fill with default clock frequency
default_basic, default_advanced, _ = calculate_advanced(24.607104)
all_latches[:, 4] = default_basic
all_latches[:, 5] = default_advanced

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
    print("conducting measurement...")

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
    print('setup done')
    nmi_num = 0
    last_nmi_cycle = 0
    wrap_cycles = 0
    while True:
        ls.communicate() # keep tasha full

        try:
            events = cf.get_events()
        except:
            print("except, finishing tas")
            while ls.communicate(): time.sleep(0.1)
            raise
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

            do_print = False
            if abs(ex_nmi_cycle-nmi_cycle) > 1000:
                print("big nmi diff:", end=" ")
                do_print = True

            if abs(busy-ex_busy) > 1:
                print("big busy diff:", end=" ")
                do_print = True

            if abs(busy-50) > 40 and apu_tot > 4 and busy < 99.999:
                print("got close:", end=" ")
                do_print = True

            if abs(ex_busy-50) > 40 and apu_tot > 4 and busy < 99.999:
                print("should be close:", end=" ")
                do_print = True

            if do_print:
                print("nmi:{} busy:{:.2f}% ex_busy:{:.2f}% "
                    "nmi_cycle:{} ex_nmi_cycle:{} apu_tot:{}".format(
                    nmi_num, busy, ex_busy, nmi_cycle, ex_nmi_cycle, apu_tot))

            nmi_num += 1

        time.sleep(0.1)

do_measure()
