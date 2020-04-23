# play back a TAS

import sys

# first, we need to load the firmware to do it
from ..firmware.playback import make_firmware
from ..firmware.bootload import do_bootload

print("Downloading playback firmware...")
do_bootload(sys.argv[1], make_firmware())
