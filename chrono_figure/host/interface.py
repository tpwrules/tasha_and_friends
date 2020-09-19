# talk to chrono figure's gateware inside the usb2snes

import struct
import time

from . import usb2snes
from ..gateware import core as gateware
from chrono_figure.eventuator.isa import *

# usb2snes expected firmware version
FIRMWARE_VERSION = 0xC10A0302

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

# program that emulates the old fixed-function Chrono Fgure
FIXED_FUNCTION_PROGRAM = [
    # we start at PC=1
    POKE(SplW.IMM_B0, 0), # build constant with bit 30 set
    POKE(SplW.IMM_B3, 1<<6),
    COPY(3, SplR.IMM_VAL),
    POKE(SplW.IMM_B0, 0x1FF), # build constant of (1<<29)-1
    POKE(SplW.IMM_B3, ((1<<29)-1)>>24),
    COPY(4, SplR.IMM_VAL),
    # we can now enable the matchers and wait for an event
    POKE(SplW.MATCH_ENABLE, 1), # value written does not matter
    # pad to PC=12
    *[BRANCH(0)]*4,

    # PC = 12: MATCH_TYPE_RESET handler
    # remember starting cycle so we can subtract it from all subsequent ones
    COPY(0, SplR.MATCH_CYCLE_COUNT),
    COPY(SplW.ALU_B1, 0),
    MODIFY(Mod.ZERO, 1), # clear currently waiting flag
    POKE(SplW.TMPA, 0), # clear event counter
    # pad to PC=20
    *[BRANCH(0)]*4,

    # PC = 20: MATCH_TYPE_NMI handler
    COPY(0, SplR.MATCH_CYCLE_COUNT), # get cycle of this event
    MODIFY(Mod.SUB_B1, 0), # subtract offset to get relative cycle
    COPY(SplW.ALU_B0, 4), # mask to 29 bits
    MODIFY(Mod.AND_B0, 0),
    COPY(2, SplR.TMPA), # get low bit of event counter
    MODIFY(Mod.GET_LSB, 2),
    MODIFY(Mod.ROTATE_RIGHT, 2),
    BRANCH(38), # continue

    # PC = 28: MATCH_TYPE_WAIT_START handler
    MODIFY(Mod.TEST_LSB, 1), # don't do anything if we are currently waiting
    BRANCH(0, Cond.Z0),
    COPY(5, SplR.MATCH_CYCLE_COUNT), # save relative cycle as wait cycle
    MODIFY(Mod.SUB_B1, 5),
    COPY(SplW.ALU_B0, 4), # mask to 29 bits
    MODIFY(Mod.AND_B0, 5),
    MODIFY(Mod.SET_LSB, 1), # and set wait flag
    # pad to PC=36
    *[BRANCH(0)]*1,

    # PC = 36: MATCH_TYPE_WAIT_END handler
    MODIFY(Mod.ZERO, 1), # clear currently waiting flag
    BRANCH(0),

    # MATCH_TYPE_NMI continued
    MODIFY(Mod.ROTATE_RIGHT, 2),
    MODIFY(Mod.ROTATE_RIGHT, 2),
    COPY(SplW.ALU_B0, 3), # set bit 30 using premade constant
    MODIFY(Mod.OR_B0, 2),
    COPY(SplW.ALU_B0, 0), # OR in the event's cycle
    MODIFY(Mod.OR_B0, 2),
    COPY(SplW.EVENT_FIFO, 2), # send the first event word
    MODIFY(Mod.TEST_LSB, 1), # get wait cycle if waiting
    BRANCH(48, Cond.Z1),
    COPY(SplW.ALU_B0, 5),
    # PC = 48
    COPY(2, SplR.TMPA), # get high bit of event counter
    MODIFY(Mod.ROTATE_RIGHT, 2),
    MODIFY(Mod.GET_LSB, 2),
    MODIFY(Mod.ROTATE_RIGHT, 2),
    MODIFY(Mod.ROTATE_RIGHT, 2),
    MODIFY(Mod.ROTATE_RIGHT, 2),
    MODIFY(Mod.OR_B0, 2), # OR in the cycle
    COPY(SplW.EVENT_FIFO, 2), # send the second event word
    MODIFY(Mod.ZERO, 1), # clear currently waiting flag
    # increment event counter
    COPY(2, SplR.TMPA),
    MODIFY(Mod.INC, 2),
    COPY(SplW.TMPA, 2),
    # reset back to 1 if it's now 4 (we don't use 0 except for reset)
    POKE(SplW.ALU_B0, 4),
    MODIFY(Mod.CMP_B0, 2),
    BRANCH(0, Cond.NE),
    POKE(SplW.TMPA, 1),
    BRANCH(0),
]

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

    # connect to the usb2snes, test communication, and validate versions. if
    # port is None, try to autodetect it. otherwise, use the given serial port.
    def connect(self, port=None):
        if self.device is not None:
            self.device.disconnect()
            self.device = None

        device = usb2snes.USB2SNES()
        if port is None:
            port = usb2snes.detect_port()
            if port is None: # couldn't be autodetected
                raise CFInterfaceError("could not autodetect usb2snes")
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

    def _read_event_fifo(self):
        new_data = struct.unpack("<128I", self.device.read_space(
            usb2snes.SPACE_CHRONO_FIGURE, ADDR_EVENT_FIFO, 512))
        return new_data[1:new_data[0]+1]

    # run a program on the eventuator and optionally wait for it to complete
    def _exec_program(self, prg, wait=False):
        if len(prg) > 250:
            raise Exception("program is too long at {} insns".format(len(prg)))

        # add instructions so we know when the program ends
        if wait:
            prg = [
                *prg,
                POKE(SplW.EVENT_FIFO, 2),
                BRANCH(0),
            ]

        # stop the eventuator (and clear match FIFO)
        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE,
            ADDR_MATCHER_CONFIG, (0).to_bytes(4, "little"))
        # clear out any old events
        self._read_event_fifo()
        # transfer in the program
        prg = struct.pack("<{}I".format(len(prg)), *(int(i) for i in prg))
        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE,
            ADDR_MATCHER_CONFIG+4, prg)
        # start the eventuator at the start of the program
        self.device.write_space(usb2snes.SPACE_CHRONO_FIGURE,
            ADDR_MATCHER_CONFIG, (1).to_bytes(4, "little"))
        # wait for it to finish (if asked)
        if wait:
            while True:
                event_data = self._read_event_fifo()
                if len(event_data) > 0 and event_data[0] == 2:
                    break
                time.sleep(0.01)

    def _make_matcher_config(self, address, match_type):
        valid_address = int(address) & 0xFFFFFF
        if valid_address != address:
            raise CFInterfaceError("invalid address '{}'".format(address))
        valid_match_type = int(match_type) & (2**gateware.MATCH_TYPE_BITS-1)
        if valid_match_type != match_type:
            raise CFInterfaceError("invalid match type '{}'".format(match_type))
        return struct.pack("<I", (valid_address + (valid_match_type<<24)))

    # configure the matchers with an iterable of (address, match_type) tuples.
    # if there are less matchers than the number of configurations, the
    # remaining matchers are disabled.
    def configure_matchers(self, configs):
        self._check_dev()

        # pack configuration into words
        config_data = []
        for config in configs:
            address, match_type = config
            config_data.append(self._make_matcher_config(address, match_type))

        # make sure we have enough matchers for the configurations
        num_matchers = gateware.NUM_MATCHERS
        if len(config_data) > num_matchers:
            raise CFInterfaceError("attempted to configure {} matchers, but "
                "the gateware has only {}".format(
                    len(config_data), num_matchers))

        # set remaining matchers to 0 = disabled
        config_data.append(b'\x00'*(4*(num_matchers-len(config_data))))
        config_data = b''.join(config_data)

        # build and run a program to configure the matchers
        prg = [POKE(SplW.MATCH_CONFIG_ADDR, 0)]
        for byte in config_data:
            prg.append(POKE(SplW.MATCH_CONFIG_DATA, byte))
        self._exec_program(prg, wait=True)

    # reset the console and start measurements
    def start_measurement(self):
        self._check_dev()

        # assert reset so the console won't interrupt us
        self.assert_reset(True)
        # start the program running (and clear the event FIFO)
        self._exec_program(FIXED_FUNCTION_PROGRAM)
        self.last_data = [] # junk all the unparsed event pieces too
        # the only event with number 0 is the first event after reset
        self.next_event_counter = 0
        # now that we know there's nothing there, let the console start back up
        # and produce new events
        self.assert_reset(False)

    # get new events and return them as an iterable of (end_cycle, wait_cycle)
    # pairs. the exact meaning is not covered here. it's recommended to wait at
    # least 100ms between calls because the usb2snes can get overwhelmed.
    def get_events(self):
        got_events = []

        event_data = self.last_data # remember any half-received events
        event_data.extend(self._read_event_fifo())

        while len(event_data) > 1: # each event is 2 words
            d0, d1 = event_data[:2]
            d0 &= 0x7FFFFFFF
            d1 &= 0x7FFFFFFF
            # bit 30 is set on the first word of each event and clear on the
            # second. skip words until we find a valid first and second. this
            # will probably trip the "missed event" handler below.
            if not (d0 & (1<<30)) and (d1 & (1<<30)):
                event_data = event_data[1:]
                continue

            # event counter is in the 29th bit of each word, and the first word
            # is the low bit
            event_counter = (d0 & (1<<29)) >> 29
            event_counter |= (d1 & (1<<29)) >> 28

            if event_counter != self.next_event_counter:
                # if we got some events, return them first. that way the caller
                # will get all the events except this one. next time they call,
                # there won't be any, so we will throw the exception.
                if len(got_events) > 0:
                    return got_events
                raise CFInterfaceError("missed event: got counter value {} but "
                    "expected value {}".format(
                        event_counter, self.next_event_counter))

            self.next_event_counter += 1
            if self.next_event_counter == 4:
                # 0 is reserved for the first event after reset
                self.next_event_counter = 1

            end_cycle = d0 & 0x1FFFFFFF
            wait_cycle = d1 & 0x1FFFFFFF

            got_events.append((end_cycle, wait_cycle))
            event_data = event_data[2:]

        # remember the leftovers for next time
        self.last_data = event_data

        return got_events
