# calculate clock generator parameters for a desired APU frequency

_sys_freq = 24.75 # generator frequency in MHz (of the internal logic).

def calculate_counter(desired):
    count = -((desired/_sys_freq)-1) * (2**24)
    count = int(count+0.5)
    count = min(max(count, 0), (2**24)-1)

    actual = count / (2**24)
    actual = (1-actual)*_sys_freq

    return count, actual
