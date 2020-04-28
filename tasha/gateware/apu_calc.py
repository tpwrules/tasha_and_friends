# calculate clock generator parameters for a desired APU frequency. see
# apu_clockgen.py for the definition.

_sys_freq = 24.75 # generator frequency in MHz (of the internal logic).

def calculate_counter(desired):
    count = -((desired/_sys_freq)-1) * (2**24)
    count = int(count+0.5)
    count = min(max(count, 0), (2**24)-1)

    actual = count / (2**24)
    actual = (1-actual)*_sys_freq

    return count, actual

def calculate_basic(desired):
    count = -((desired/_sys_freq)-1) * (2**24)
    count = int(count+0.5)
    count = min(max(count, 0), (2**24)-1)

    count &= 0x0FFFF0

    actual = count / (2**24)
    actual = (1-actual)*_sys_freq

    return count>>4, actual

def calculate_advanced(desired, jitter=0, jitter_mode=0, polarity=0):
    count, actual = calculate_counter(desired)

    basic = (count & 0x0FFFF0) >> 4
    advanced = ((count >> 16) & 0xF0) | (count & 0xF)

    advanced |= min(max(jitter, 0), 7) << 8
    if jitter_mode:
        advanced |= 0x4000
    if polarity:
        advanced |= 0x8000

    return basic, advanced, actual
