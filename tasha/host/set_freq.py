# set the APU frequency. opens up a REPL with a "set_freq" function which takes
# several parameters:
#   desired: desired APU frequency in MHz
#   jitter: maximum jitter amount
#   jitter_mode: how the jitter LFSR advances
#   polarity: which clock cycles are dropped
# when called, the new parameters are calculated and a command is sent to
# configure th clock generator. if any parameters are None (or left out) then
# they are unchanged

# to quote apu_clockgen.py:

# The "jitter" input controls the maximum delay added by the jitter unit. A
# setting of 0 turns off jitter, a setting of 1 delays the pulse skipping by 0
# or 1 cycles, a setting of 2 delays 0-3 cycles, etc., up to 7 which delays
# 0-127 cycles. The "jitter_mode" input controls how the LFSR is advanced: if 0,
# the LFSR is advanced every clock cycle; if 1, it's advanced every time a clock
# pulse is skipped.

# NOTE: if the counter value is high so pulses are frequently skipped (i.e. a
# low frequency is being output), then a high amount of jitter may cause the
# pulse skips to be skipped and so unexpectedly raise the output frequency.

# The "polarity" input controls which clock pulses are skipped. If 1, then the
# high pulses are skipped (010 -> 000), and if 0, the low pulses are skipped
# (101 -> 111).

# The effect (if any) of the above settings (except for "counter") is not
# particularly understood, but they are available for experimentation.

import sys
import struct
import serial
import code

import crcmod.predefined
crc_16_kermit = crcmod.predefined.mkPredefinedCrcFun("kermit")

from ..gateware.apu_calc import calculate_advanced

# first, we need to load the firmware to do it
from ..firmware.set_freq import make_firmware
from .bootload import do_bootload

print("Downloading firmware...")
do_bootload(sys.argv[1], make_firmware())

print("Reestablishing connection...")
_port = serial.Serial(port=sys.argv[1], baudrate=2_000_000, timeout=0.1)

curr_desired = 24.607104
curr_jitter = 0
curr_jitter_mode = 0
curr_polarity = 0

def set_freq(*, desired=None, jitter=None, jitter_mode=None, polarity=None):
    global curr_desired, curr_jitter, curr_jitter_mode, curr_polarity
    if desired is not None: curr_desired = desired
    if jitter is not None: curr_jitter = jitter
    if jitter_mode is not None: curr_jitter_mode = jitter_mode
    if polarity is not None: curr_polarity = polarity

    basic, advanced, actual = calculate_advanced(
        curr_desired, curr_jitter, curr_jitter_mode, curr_polarity)

    data = struct.pack("<3H",
        0x2002, # command
        basic, advanced,
    )
    data += crc_16_kermit(data).to_bytes(2, byteorder="little")
    _port.write(data)
    _port.flush()

    # round to 1Hz
    return int(actual*1e6 + 0.5)/1e6

code.interact(local={"set_freq": set_freq, "_port":_port},
    banner="Configure the frequency with set_freq(desired, jitter, "
    "jitter_mode, polarity). Parameters not provided will be unchanged.")
