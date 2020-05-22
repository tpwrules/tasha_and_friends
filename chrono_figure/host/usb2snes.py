# talk to the usb2snes (in only the ways chrono figure needs)

import struct
from collections import namedtuple

import serial
import serial.tools.list_ports

# if there is exactly one USB2SNES device attached, return its port (suitable
# for passing to connect()). otherwise, if there are no devices or more than
# one, return None.
def detect_port():
    got_port = None
    for port in serial.tools.list_ports.comports():
        if (port.vid, port.pid) == (0x1209, 0x5A22):
            if got_port is not None: # there are multiple ports
                return None
            got_port = port.device

    return got_port

OP_GET = 0
OP_PUT = 1
OP_RESET = 8
OP_BOOT = 9
OP_INFO = 11
OP_MENU_RESET = 12

SPACE_SNES = 1
SPACE_CHRONO_FIGURE = 5

FLAG_NONE = 0
FLAG_NORESP = 64

class USB2SNESError(Exception): pass

class Timeout(USB2SNESError): pass

USB2SNESInfo = namedtuple("USB2SNESInfo", [
    "fw_version", # CONFIG_FWVER: firmware version as a 32 bit number
    "fw_version_string", # firmware version string displayed in the menu
    "device_name", # DEVICE_NAME: "sd2snes Mk.II" or "sd2snes Mk.III"
    "feature_byte", # low byte of active FPGA feature bits. consult usb2snes's
                    # src/fpga_spi.c for definitions
    "current_rom", # file name of the currently executing ROM
])

class USB2SNES:
    def __init__(self):
        # we don't have a port until we're connected
        self.port = None

    def _ser_read(self, length):
        if self.port is None:
            raise USB2SNESError("not connected")

        read = b""
        while length > 0:
            new = self.port.read(length)
            if len(new) == 0:
                raise Timeout("read timeout")
            read += new
            length -= len(new)
        return read

    def _ser_write(self, data):
        if self.port is None:
            raise USB2SNESError("not connected")

        sent_len = 0
        while sent_len != len(data):
            sent_len += self.port.write(data[sent_len:])

        self.port.flush()

    def connect(self, port):
        if self.port is not None:
            self.disconnect()

        port = serial.Serial(port=port, baudrate=9600, timeout=3)
        self.port = port

    def disconnect(self):
        if self.port is None:
            return

        port = self.port
        self.port = None
        try:
            port.close()
        except:
            pass

    # send out a usb2snes command. for most opcodes, arg_data is additional
    # binary data that encodes the opcode parameters. for OP_GET and OP_PUT it's
    # an (address, size) tuple to operate on. if resp is True, then the usb2snes
    # is told to respond. this function DOES NOT read or parse the response.
    def _send_command(self, opcode, space, arg_data=None, resp=False):
        flags = FLAG_NONE if resp else FLAG_NORESP
        cmd_buf = b'USBA' + bytes([opcode, space, flags])

        if opcode == OP_GET or opcode == OP_PUT:
            # pad out to the size field
            cmd_buf += b'\x00'*(252-len(cmd_buf))
            # then write the size, followed by the address
            cmd_buf += struct.pack('>II', arg_data[1], arg_data[0])
        else:
            # pad out to the argument field
            cmd_buf += b'\x00'*(256-len(cmd_buf))
            # add any argument data
            if arg_data is not None:
                arg_len = min(512-len(cmd_buf), len(arg_data))
                cmd_buf += arg_data[:arg_len]

        # pad out to the 512 byte packet size
        cmd_buf += b'\x00'*(512-len(cmd_buf))
        # and send everything on
        self._ser_write(cmd_buf)

    # reset the currently running game (or the menu, if it's currently running)
    def reset_console(self):
        self._send_command(OP_RESET, SPACE_SNES)

    # reset back to the menu. has no effect if the menu is currently running,
    def reset_to_menu(self):
        self._send_command(OP_MENU_RESET, SPACE_SNES)

    # boot the SNES ROM off the SD card with the given file name
    def boot_rom(self, filename):
        filename = filename.encode("ascii")
        if b"." not in filename:
            # for some reason the microcontroller firmware crashes hard on
            # extensionless filenames. the console must then be power cycled.
            raise USB2SNESError("Filename '{}' does not have a period. "
                "Trying to boot it would crash the USB2SNES.".format(filename))
        self._send_command(OP_BOOT, SPACE_SNES, filename)

    # read various pieces of information about what's going on
    def get_info(self):
        # ask for the information
        self._send_command(OP_INFO, SPACE_SNES, resp=True)
        # it comes back in its own packet
        info_packet = self._ser_read(512)

        # convert some packet bytes to a string
        def tostr(b):
            # remove all the null terminators
            try:
                b = b[:b.index(b'\x00')]
            except ValueError:
                pass # there weren't any

            return b.decode("ascii")

        return USB2SNESInfo(
            fw_version=struct.unpack(">I", info_packet[256:260])[0],
            fw_version_string=tostr(info_packet[260:260+64]),
            device_name=tostr(info_packet[260+64:260+128]),
            feature_byte=info_packet[6],
            current_rom=tostr(info_packet[16:256])
        )

    # read some data from a given memory space
    def read_space(self, space, address, size):
        # ask to read the data
        self._send_command(OP_GET, space, [address, size])
        # receive enough 512 byte blocks to get all of it
        num_blocks = (size+511) >> 9
        data = self._ser_read(num_blocks*512)
        # return only what was asked for
        return data[:size]

    # write some data to a given memory space
    def write_space(self, space, address, data):
        # say that we're writing some data
        self._send_command(OP_PUT, space, [address, len(data)])
        # pad it out to full 512 byte blocks
        if len(data) % 512 > 0:
            data += b'\x00'*(512-(len(data)%512))
        # then send it along
        self._ser_write(data)
