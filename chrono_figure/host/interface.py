# talk to chrono figure's gateware inside the usb2snes

import struct

from . import usb2snes
from ..gateware import core as gateware

# usb2snes expected firmware version
FIRMWARE_VERSION = 0xC10A0306

# chrono figure address space addresses. matches usb2snes's src/chrono_figure.c
ADDR_GATEWARE_VERSION = 0x00000000
ADDR_LOOPBACK = 0x00000004
ADDR_RESET = 0x00000008
ADDR_SAVE_INHIBIT = 0x0000000C

ADDR_CLEAR_SAVE_RAM = 0x00000010
CLEAR_SAVE_RAM_KEY = 0x05C1EA12

ADDR_MATCHER_CONFIG = 0x10000000
ADDR_EVENT_FIFO = 0x80000000

class CFInterfaceError(Exception): pass

class ChronoFigureInterface:
    def __init__(self):
        # the usb2snes device. we don't have one until we're connected.
        self.device = None

    def _check_dev(self):
        if self.device is None:
            raise CFInterfaceError("not connected")

    # connect to the usb2snes, test communication, and validate versions
    def connect(self, port):
        if self.device is not None:
            self.device.disconnect()
            self.device = None

        device = usb2snes.USB2SNES()
        device.connect(port)

        # make sure the usb2snes is responsive. if it is, validate the returned
        # firmware version
        info = device.get_info()
        if info.fw_version != FIRMWARE_VERSION:
            m = ("Incorrect usb2snes firmware version: received 0x{:08X} but "
                "expected 0x{:08X}. ").format(info.fw_version, FIRMWARE_VERSION)
            if (info.fw_version >> 30) != 3:
                # top 2 bits are set for chrono-figure-enabled firmware versions
                m += ("The installed firmware does not appear to be Chrono "
                    "Figure enabled. ")
            m += "Please put the correct firmware.img/3 file on your SD card."
            raise CFInterfaceError(m)

        # make sure the usb2snes can access the gateware through our special
        # address space. if it can, validate the gateware's version too.
        gw_ver = struct.unpack("<I", device.read_space(
            usb2snes.SPACE_CHRONO_FIGURE, ADDR_GATEWARE_VERSION, 4))[0]
        if gw_ver != gateware.GATEWARE_VERSION:
            raise CFInterfaceError("Incorrect Chrono Figure gateware version: "
                "received {} but expected {}. Please put the correct "
                "fpga_base.bit/3 file on your SD card.".format(
                    gw_ver, gateware.GATEWARE_VERSION))

        # everything checks out
        self.device = device

    def disconnect(self):
        if self.device is not None:
            self.device.disconnect()
            self.device = None

    # assert console reset from the cart (cannot reset PPUs). the sd2snes does
    # not see the reset so e.g. save RAM will not be saved. automatically
    # cleared when a ROM is loaded.
    def assert_reset(self, do_assert):
        self._check_dev()
        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE, ADDR_RESET,
            struct.pack("<I", 1 if do_assert else 0))

    # prevent the sd2snes from writing save RAM to SD card. un-preventing forces
    # an immediate save. automatically cleared (but data is not saved) when a
    # ROM is loaded.
    def prevent_saving(self, do_prevent):
        self._check_dev()
        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE, ADDR_SAVE_INHIBIT,
            struct.pack("<I", 1 if do_prevent else 0))

    # fill save RAM with 0xFF as if it had never been written. this should not
    # destroy the save on the SD card if saving is prevented, but I make no
    # guarantees! may have "exciting" effects if the console is not in reset.
    def destroy_save_ram(self):
        self._check_dev()
        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE,
            ADDR_CLEAR_SAVE_RAM, struct.pack("<I", CLEAR_SAVE_RAM_KEY))
