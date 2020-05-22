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
        # what number we expect the next event to be. if it's not this, then we
        # must have missed one
        self.next_event_counter = None
        # leftover event data that's not yet complete
        self.last_data = []

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
        self.next_event_counter = None
        self.last_data = []

    def disconnect(self):
        if self.device is not None:
            self.device.disconnect()
            self.device = None

        self.next_event_counter = None
        self.last_data = []

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

    # configure the matchers with an iterable of (address, match_type) tuples.
    # if there are less matchers than the number of configurations, the
    # remaining matchers are disabled.
    def configure_matchers(self, configs):
        self._check_dev()

        # pack configuration into words
        config_data = []
        for config in configs:
            address, match_type = config
            valid_address = int(address) & 0xFFFFFF
            if valid_address != address:
                raise CFInterfaceError("invalid address '{}'".format(address))
            valid_match_type = int(match_type) & (2**gateware.MATCH_TYPE_BITS-1)
            if valid_match_type != match_type:
                raise CFInterfaceError("invalid match type '{}'".format(
                    match_type))
            config_data.append(struct.pack("<I", 
                (valid_address + (valid_match_type<<24))))

        # make sure we have enough matchers for the configurations
        # more than 16 breaks things for some reason
        num_matchers = 16 # gateware.NUM_MATCHERS
        if len(config_data) > num_matchers:
            raise CFInterfaceError("attempted to configure {} matchers, but "
                "the gateware has only {}".format(
                    len(config_data, num_matchers)))

        # set remaining matchers to 0 = disabled
        config_data.append(b'\x00'*(4*(num_matchers-len(config_data))))
        config_data = b''.join(config_data)

        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE,
            ADDR_MATCHER_CONFIG, config_data)

    # reset the console and start measurements
    def start_measurement(self):
        self._check_dev()

        # assert reset so the console won't interrupt us
        self.assert_reset(True)
        # the event FIFO is 128 words, so we read 512 bytes to guarantee we've
        # got all the old events out of it
        self.device.read_space(usb2snes.SPACE_CHRONO_FIGURE,
            ADDR_EVENT_FIFO, 512)
        # the only event with number 0 is the first event after reset
        self.next_event_counter = 0
        # now that we know there's nothing there, let the console start back up
        # and produce new events
        self.assert_reset(False)

    # get new events and return them as an iterable of (nmi_cycle, wait_cycle)
    # pairs. the exact meaning is not covered here. it's recommended to wait at
    # least 100ms between calls because the usb2snes can get overwhelmed.
    def get_events(self):
        got_events = []

        event_data = self.last_data # remember any half-received events
        # empty the event FIFO of all its 32 bit data words
        new_data = struct.unpack("<128I", self.device.read_space(
            usb2snes.SPACE_CHRONO_FIGURE, ADDR_EVENT_FIFO, 512))
        # words with the high bit set are invalid (the FIFO was empty)
        event_data.extend(filter(lambda w: not (w & (1<<31)), new_data))

        while len(event_data) > 1: # each event is 2 words
            d0, d1 = event_data[:2]
            # bit 30 is set on the first word of each event
            if not (d0 & (1<<30)): # so skip words until we find one
                event_data = event_data[1:]
                continue

            # event counter is in the 29th bit of each word, and the first word
            # is the low bit
            event_counter = (d0 & (1<<29)) >> 29
            event_counter |= (d1 & (1<<29)) >> 28

            if event_counter != self.next_event_counter:
               raise CFInterfaceError("missed event: got counter value {} but "
                   "expected value {}".format(
                       event_counter, self.next_event_counter))

            self.next_event_counter += 1
            if self.next_event_counter == 4:
                # 0 is reserved for the first event after reset
                self.next_event_counter = 1

            nmi_cycle = d0 & 0x1FFFFFFF
            wait_cycle = d1 & 0x1FFFFFFF

            got_events.append((nmi_cycle, wait_cycle))
            event_data = event_data[2:]

        # remember the leftovers for next time
        self.event_data = event_data

        return got_events
