# talk to the usb2snes (in only the ways chrono figure needs)

import struct
from collections import namedtuple
import pathlib

import serial
import serial.tools.list_ports

# SOME WORDS ON FILE PATHS

# A USB2SNES path describes the path to a file or directory on the SD card.
# USB2SNES paths operate essentially like Unix paths: forward slashes separate
# directories, '.' and '..' represent current and one-level-up directories
# respectively. However, note that paths are ASCII-encoded, cannot contain 0x00
# characters, and are limited to 255 bytes. Paths are always relative to the
# root of the SD card: paths "/cool.file" and "cool.file" always refer to
# "cool.file" in the root directory.

# Errors during certain file operations can crash the USB2SNES and require that
# the console be power-cycled. This includes reading nonexistent files, and
# (inexplicably) attempting to boot a ROM without a period (.) in its name.

# To mitigate the danger, each component of the path is listed with the LS
# command to verify that the next component exists. This also allows for more
# precise error messages. LS results are cached to improve performance. If this
# is undesirable, then the 'check' parameter can be set to False when calling a
# function that deals with files (though the cache will still be used).



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
OP_LS = 4
OP_MKDIR = 5
OP_RM = 6
OP_RESET = 8
OP_BOOT = 9
OP_INFO = 11
OP_MENU_RESET = 12

SPACE_FILE = 0
SPACE_SNES = 1
SPACE_CHRONO_FIGURE = 5

FLAG_NONE = 0
FLAG_NORESP = 64

class USB2SNESError(Exception): pass

class Timeout(USB2SNESError): pass

class PathError(USB2SNESError):
    def __init__(self, path, problem, component=None):
        self.path = path
        self.problem = problem
        self.component = component

    def __str__(self):
        if self.component is None:
            return "Path '{}': {}".format(self.path, self.problem)
        else:
            return "Path '{}': '{}' {}".format(
                self.path, self.component, self.problem)

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
        self._dir_cache = {"": None} # holds the root directory

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
        self._dir_cache = {"": None}
        try:
            port.close()
        except:
            pass

    # send out a usb2snes command. arg_size is the 32 bit size at [252:256].
    # arg_data is additional binary data at [256:]. if resp is True, then the
    # usb2snes is told to respond. this function DOES NOT read or parse the
    # response.
    def _send_command(self, opcode, space,
            arg_size=0, arg_data=b'', resp=False):
        flags = FLAG_NONE if resp else FLAG_NORESP
        cmd_buf = b'USBA' + bytes([opcode, space, flags])

        # pad to and then write out the size field
        cmd_buf += b'\x00'*(252-len(cmd_buf))
        cmd_buf += struct.pack(">I", arg_size)
        # add the rest of the argument data
        cmd_buf += arg_data[:256]
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
    def boot_rom(self, path, check=True):
        encoded_path, parts, kind = self.parse_path(path, check=check)
        if kind != "unknown" and kind != "file":
            raise PathError(path, "does not exist", parts[-1])
        if "." not in parts[-1]:
            raise PathError(path, "name has no period (.)", parts[-1])
        self._send_command(OP_BOOT, SPACE_SNES, arg_data=encoded_path)

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
        self._send_command(OP_GET, space,
            arg_size=size, arg_data=struct.pack('>I', address))
        # receive enough 512 byte blocks to get all of it
        num_blocks = (size+511) >> 9
        data = self._ser_read(num_blocks*512)
        # return only what was asked for
        return data[:size]

    # write some data to a given memory space
    def write_space(self, space, address, data):
        # say that we're writing some data
        self._send_command(OP_PUT, space,
            arg_size=len(data), arg_data=struct.pack('>I', address))
        # pad it out to full 512 byte blocks
        if len(data) % 512 > 0:
            data += b'\x00'*(512-(len(data)%512))
        # then send it along
        self._ser_write(data)


    # parse a path and return the final encoded filename, the list of
    # components (parts), and what kind of thing the last component is
    def parse_path(self, path, check=True):
        # make sure the path actually is ASCII before we do anything to it
        try:
            path.encode("ascii")
        except UnicodeEncodeError as e:
            raise PathError(path, "", str(e)) from None

        # canonicalize the path to remove "."s, ".."s, and extra "/"s
        parts = [""] # root directory is at the start
        for part in path.split("/"):
            if part == "" or part == ".":
                continue
            elif part == "..":
                if len(parts) == 1:
                    raise PathError(path, "traversing above root directory",
                        part) from None
                parts.pop()
            else:
                parts.append(part)

        # validate that everything exists along the way
        curr_dir = self._dir_cache
        for part_i, part in enumerate(parts):
            # the current directory is the one that allegedly contains this part
            if curr_dir is None: # we know it exists, but not what's in it
                if not check: # and we're not allowed to go ask
                    break
                # figure that out (list_dir will update the cache)
                self.list_dir("/".join(parts[:part_i]))
                curr_dir = prev_dir[parts[part_i-1]]
            # we don't want to traverse into the last part
            if part_i == len(parts)-1: break

            prev_dir = curr_dir
            try:
                curr_dir = curr_dir[part]
            except KeyError:
                raise PathError(path, "does not exist", part) from None
            if curr_dir is not None and not isinstance(curr_dir, dict):
                raise PathError(path, "not a directory", part)

        # if we know what's in the directory, figure out what we're pointing to
        if curr_dir is not None:
            try:
                entry = curr_dir[parts[-1]]
                if entry is None or isinstance(entry, dict):
                    kind = "dir"
                else:
                    kind = "file"
            except KeyError:
                kind = "nothing"
        else:
            kind = "unknown"

        validated_path = "/".join(parts[1:]).encode("ascii")
        if len(validated_path) > 255:
            raise PathError(path, "too long", validated_path)
        return validated_path, parts, kind


    def list_dir(self, path, check=True):
        encoded_path, parts, kind = self.parse_path(path, check=check)
        if kind != "unknown":
            if kind == "nothing":
                raise PathError(path, "does not exist", parts[-1])
            elif kind != "dir":
                raise PathError(path, "not a directory", parts[-1])
        self._send_command(OP_LS, SPACE_FILE, arg_data=encoded_path, resp=True)
        resp = self._ser_read(512)
        if resp[5]:
            raise USB2SNESError("{}: failed to list".format(path))

        list_result = {}
        finished = False
        while not finished:
            data = self._ser_read(512)
            while len(data) > 0:
                if data[0] == 0xFF: # no more entries
                    finished = True
                    break
                elif data[0] == 0x02: # another packet is coming
                    break

                is_dir = data[0] == 0
                name_end = data[1:].index(b'\x00')+1
                filename = data[1:name_end].decode("ascii")
                data = data[name_end+1:]

                if filename == "." or filename == "..": continue
                if is_dir:
                    list_result[filename] = None
                else:
                    list_result[filename] = "a file"

        # update the cache with what we learned (if the parent directory's
        # contents are in the cache)
        curr_dir = self._dir_cache
        for part in parts[:-1]:
            try:
                curr_dir = curr_dir[part]
            except KeyError:
                break
            if curr_dir is None:
                break
        else:
            curr_dir[parts[-1]] = list_result

        return list_result

    # create an empty directory
    def make_dir(self, path, check=True):
        encoded_path, parts, kind = self.parse_path(path, check=check)
        if kind != "unknown":
            if kind != "nothing":
                raise PathError(path, "already exists", parts[-1])

        try:
            self._send_command(OP_MKDIR, SPACE_FILE,
                arg_data=encoded_path, resp=True)
            resp = self._ser_read(512)
            if resp[5]:
                raise USB2SNESError("{}: failed to create".format(path))
        except:
            # no idea what happened now
            self._dir_cache = {"": None}
            raise

        # update the cache if the parent directory's contents are in it
        curr_dir = self._dir_cache
        for part in parts[:-1]:
            try:
                curr_dir = curr_dir[part]
            except KeyError:
                break
            if curr_dir is None:
                break
        else:
            curr_dir[parts[-1]] = {}

    # read a file from the SD card and return its data as bytes
    def read_file(self, path, check=True):
        encoded_path, parts, kind = self.parse_path(path, check=check)
        if kind != "unknown":
            if kind == "nothing":
                raise PathError(path, "does not exist", parts[-1])
            elif kind != "file":
                raise PathError(path, "not a file", parts[-1])
        self._send_command(OP_GET, SPACE_FILE, arg_data=encoded_path, resp=True)

        resp = self._ser_read(512)
        if resp[5]:
            # read errors will most probably crash the USB2SNES
            raise USB2SNESError("{}: failed to read".format(path))

        file_size = struct.unpack(">I", resp[252:256])[0]
        num_blocks = (file_size+511) >> 9
        data = []
        for block in range(num_blocks):
            data.append(self._ser_read(512))
        data = b''.join(data)[:file_size]

        return data

    # fill some file with bytes on the SD card. if it exists, the file is
    # overwritten
    def write_file(self, data, path, check=True):
        encoded_path, parts, kind = self.parse_path(path, check=check)
        if kind != "unknown":
            if kind != "file" and kind != "nothing":
                raise PathError(path, "not a file", parts[-1])

        try:
            self._send_command(OP_PUT, SPACE_FILE,
                arg_size=len(data), arg_data=encoded_path, resp=True)
            resp = self._ser_read(512)
            if resp[5]:
                raise USB2SNESError("{}: failed to write".format(path))

            # pad the file data out to full 512 byte blocks
            if len(data) % 512 > 0:
                data += b'\x00'*(512-(len(data)%512))
            # then send it along
            self._ser_write(data)
        except:
            # no idea what happened now
            self._dir_cache = {"": None}
            raise

        # update the cache if the parent directory's contents are in it
        curr_dir = self._dir_cache
        for part in parts[:-1]:
            try:
                curr_dir = curr_dir[part]
            except KeyError:
                break
            if curr_dir is None:
                break
        else:
            curr_dir[parts[-1]] = "a file"

    # remove a file (or empty directory) from the SD card
    def remove_file(self, path, check=True):
        encoded_path, parts, kind = self.parse_path(path, check=check)
        if kind != "unknown":
            if kind == "nothing":
                raise PathError(path, "does not exist", parts[-1])
            if kind == "dir" and check:
                contents = self.list_dir(path)
                if len(contents) > 0:
                    raise PathError(path, "directory not empty", parts[-1])

        try:
            self._send_command(OP_RM, SPACE_FILE,
                arg_data=encoded_path, resp=True)
            resp = self._ser_read(512)
            if resp[5]:
                raise USB2SNESError("{}: failed to remove".format(path))
        except:
            # no idea what happened now
            self._dir_cache = {"": None}
            raise

        # update the cache if the parent directory's contents are in it
        curr_dir = self._dir_cache
        for part in parts[:-1]:
            try:
                curr_dir = curr_dir[part]
            except KeyError:
                break
            if curr_dir is None:
                break
        else:
            del curr_dir[parts[-1]]


def file_action(args, usb2snes):
    if args.action == "ls":
        contents = usb2snes.list_dir(args.path)
        for content, properties in contents.items():
            if not args.all and content.startswith("."):
                continue
            if properties is None:
                print(content+"/")
            else:
                print(content)
    elif args.action == "get":
        dest = pathlib.Path(args.dest_path)
        # ensure the destination's parent exists so we can (probably) open the
        # file to write it once we receive it
        dest = dest.parent.resolve(strict=True)/dest.name

        # make sure there aren't any problems in the given path
        encoded_path, parts, _ = usb2snes.parse_path(args.source_path)
        if dest.is_dir():
            dest = dest/parts[-1]

        print(encoded_path.decode("ascii"), "->", dest)
        data = usb2snes.read_file(args.source_path)
        dest.write_bytes(data)
    elif args.action == "put":
        source = pathlib.Path(args.source_path).resolve(strict=True)
        dest = args.dest_path
        encoded_path, parts, kind = usb2snes.parse_path(dest)
        if dest.endswith("/") and kind == "file":
            raise PathError(dest, "not a directory", parts[-1])
        if kind == "dir":
            dest += ("/" + source.name)
            encoded_path, _, _ = usb2snes.parse_path(dest)

        print(source, "->", encoded_path.decode("ascii"))
        data = source.read_bytes()
        usb2snes.write_file(data, dest)
    elif args.action == "rm":
        usb2snes.remove_file(args.path)
    elif args.action == "mkdir":
        usb2snes.make_dir(args.path)


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Command USB2SNES.")
    parser.add_argument('--port', type=str, help="Serial port USB2SNES is "
        "attached to. Port is autodetected if not specified.")
    sps = parser.add_subparsers(required=True, help="Action to perform.")

    p_boot = sps.add_parser('boot',
        description="Start a ROM off SD card.")
    p_boot.add_argument('path', type=str, help="Path to ROM.")
    p_boot.set_defaults(action="boot")

    p_reset = sps.add_parser('reset', description="Reset the console.")
    p_reset.add_argument('-m', '--menu', action="store_true",
        help="Reset back to menu instead of the game.")
    p_reset.set_defaults(action="reset")

    p_ls = sps.add_parser('ls', description="List directory on SD card.")
    p_ls.add_argument('path', type=str, default="/", nargs='?',
        help="Path to directory on SD card.")
    p_ls.add_argument('-a', '--all', action="store_true",
        help="List files beginning with a period (.).")
    p_ls.set_defaults(action="ls")

    p_get = sps.add_parser('get', description="Read a file from SD card.")
    p_get.add_argument('source_path', type=str,
        help="Path to file on SD card.")
    p_get.add_argument('dest_path', type=str, default=".", nargs='?',
        help="Path to file on computer.")
    p_get.set_defaults(action="get")

    p_put = sps.add_parser('put', description="Write a file to SD card.")
    p_put.add_argument('source_path', type=str,
        help="Path to file on computer.")
    p_put.add_argument('dest_path', type=str, default="", nargs='?',
        help="Path to file on SD card.")
    p_put.set_defaults(action="put")

    p_rm = sps.add_parser('rm', description="Remove a file from SD card.")
    p_rm.add_argument('path', type=str,
        help="Path to file on SD card.")
    p_rm.set_defaults(action="rm")

    p_mkdir = sps.add_parser('mkdir',
        description="Create a directory on SD card.")
    p_mkdir.add_argument('path', type=str,
        help="Path to directory on SD card.")
    p_mkdir.set_defaults(action="mkdir")

    args = parser.parse_args()

    usb2snes = USB2SNES()
    if args.port is None:
        port = detect_port()
        if port is None:
            print("Could not detect USB2SNES.")
            exit(1)
    else:
        port = args.port
    usb2snes.connect(port)
    # test responsiveness. we may use the result in the future
    info = usb2snes.get_info()

    if args.action == "boot":
        try:
            usb2snes.boot_rom(args.path)
        except PathError as e:
            print(str(e))
        time.sleep(0.2) # wait for the command to make it
    elif args.action == "reset":
        if args.menu:
            usb2snes.reset_to_menu()
        else:
            usb2snes.reset_console()
        time.sleep(0.2) # wait for the command to make it
    else:
        try:
            file_action(args, usb2snes)
        except PathError as e:
            print(str(e))

    usb2snes.disconnect()
