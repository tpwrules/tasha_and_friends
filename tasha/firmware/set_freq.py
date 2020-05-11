# firmware to set the APU frequency

# notational notes:
# boneless is a word-based architecture, it has no concept of the 8 bit byte.
# but we do, so we have to define what a word means.
# * a "word" is a 16 bit unsigned integer, transmitted and stored in
#   little-endian byte order.
# * an "address" selects one "word".

# we define "CRC" as CRC-16/KERMIT (as defined by anycrc). it's computed in
# little-endian order, such that the CRC of words [0x0102, 0x0304] equals the 
# CRC of bytes [0x2, 0x1, 0x3, 0x4]

# command packet format:
# first word: header (always 0x7A5A)
# second word: command
#   bits 7-0: number of parameters, always 2
#   bits 15-8: command number, always 0x20
# third word: APU frequency adjust (basic)
# fourth word: APU frequency adjust (advanced)
# fifth word: CRC of previous words

# consult snes.py for definition of the third and fourth word. if the command is
# invalid or the CRC fails or whatever, the command just gets ignored.

# Note: also accepts the bootloader hello command (command number 1 with 2
# unused parameters)

import random

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from .bonetools import *

from ..gateware.periph_map import p_map

__all__ = ["make_firmware"]

def make_firmware():
    r = RegisterManager(
        "R6:comm_word R5:rxlr R4:temp "
        "R2:param2 R1:param1 R0:command")
    fw = [
        # start from "reset" (i.e. download is finished)
        # we just use the free register window the bootloader gives us

        # set UART receive timeout to about 100ms. this way reception will be
        # reset if we don't receive a complete command.
        MOVI(R0, int((12e6*(100/1000))/256)),
        STXA(R0, p_map.uart.w_rt_timer),

    L("main_loop"),
        # clear any UART errors and reset the receive timeout
        MOVI(r.temp, 0xFFFF),
        STXA(r.temp, p_map.uart.w_error_clear),

    L("rx_header_lo"), # wait to get the header low byte (0x5A)
        # check for UART errors (timeouts, overflows, etc.)
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp), # set flags
        BZ0("main_loop"),
        # get a new byte and check if it matches. we don't bother checking if we
        # got anything because it won't match in that case and we just loop
        # until it does
        LDXA(r.temp, p_map.uart.r_rx_hi),
        CMPI(r.temp, 0x5A << 7),
        BNE("rx_header_lo"),

    L("rx_header_hi"), # do the same for the header high byte (0x7A)
        # check for UART errors (timeouts, overflows, etc.)
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp), # set flags
        BZ0("main_loop"),
        # get a new byte and check if it matches. if we didn't get anything we
        # try to receive the high byte again.
        LDXA(r.temp, p_map.uart.r_rx_hi),
        ADD(r.temp, r.temp, r.temp),
        BC1("rx_header_hi"),
        # if we actually got the first byte, go back to looking for the second
        CMPI(r.temp, 0x5A << 8),
        BEQ("rx_header_hi"),
        CMPI(r.temp, 0x7A << 8),
        BNE("main_loop"),

        # we have confirmed both header bytes. who knows what the CRC is now.
        STXA(r.temp, p_map.uart.w_crc_reset), # write something to reset it

        # receive the command packet
        JAL(r.rxlr, "rx_comm_word"),
        MOV(r.command, r.comm_word),
        JAL(r.rxlr, "rx_comm_word"),
        MOV(r.param1, r.comm_word),
        JAL(r.rxlr, "rx_comm_word"),
        MOV(r.param2, r.comm_word),
        JAL(r.rxlr, "rx_comm_word"),
        LDXA(r.temp, p_map.uart.r_crc_value),
        AND(r.temp, r.temp, r.temp),
        BNZ("main_loop"), # ignore packets with incorrect CRC

        CMPI(r.command, 0x0102),
        BEQ("handle_hello"),
        CMPI(r.command, 0x2002),
        BNE("main_loop"), # invalid command

        # update APU registers with command values
        STXA(r.param1, p_map.snes.w_apu_freq_basic),
        STXA(r.param2, p_map.snes.w_apu_freq_advanced),
        # write something (anything) to force a latch so the clock generator
        # gets updated with the values we just wrote
        STXA(R0, p_map.snes.w_force_latch),

        J("main_loop"),

    L("handle_hello"),
        # we got a valid hello. reset into the bootloader.
        MOVI(R0, 0xFADE),
        MOVI(R1, 0xDEAD),
        STXA(R0, p_map.reset_req.w_enable_key_fade),
        STXA(R1, p_map.reset_req.w_perform_key_dead),
        J(-1), # hang until it happens

    L("rx_comm_word"),
        # check for UART errors (timeouts, overflows, etc.)
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp), # set flags
        BZ0("main_loop"), # ignore errors and reset reception
        # check if we have a new byte
        LDXA(r.comm_word, p_map.uart.r_rx_lo),
        ROLI(r.comm_word, r.comm_word, 1),
        BS1("rx_comm_word"),

    L("rcw_hi"),
        # check again for UART errors
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp),
        BZ0("main_loop"),
        # and see if we have the high byte yet
        LDXA(r.temp, p_map.uart.r_rx_hi),
        ADD(r.temp, r.temp, r.temp),
        BC1("rcw_hi"),
        # put the bytes together
        OR(r.comm_word, r.comm_word, r.temp),
        # and we are done
        JR(r.rxlr, 0),
    ]

    assembled_fw = Instr.assemble(fw)
    # don't bother measuring the length, it's assuredly less than 16,384 words

    return assembled_fw
