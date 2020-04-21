# firmware for the system bootloader

# notational notes:
# boneless is a word-based architecture, it has no concept of the 8 bit byte.
# but we do, so we have to define what a word means.
# * a "word" is a 16 bit unsigned integer, transmitted and stored in
#   little-endian byte order.
# * an "address" selects one "word".

# UART command packet format:
# first word: command
#   bits 7-0: number of words to follow, excluding CRC word and command word
#   bits 15-8: command number, defined later
# next words: command parameters, as defined in command
# last word: CRC-16/KERMIT result, calculated over all preceding words in
# little-endian order: CRC([0x0102, 0x0304]) = CRC([0x2, 0x1, 0x4, 0x3])

# UART response packet format: (in response to command)
# first word: result
#   bits 7-0: number of words to follow, excluding CRC word and result word
#   bits 15-8: result code, defined later
# next words: result information, as defined in result
# last word: CRC-16/KERMIT result, calculated over all preceding words in
# little-endian order: CRC([0x0102, 0x0304]) = CRC([0x2, 0x1, 0x4, 0x3])

# "number of words to follow" for both cases, i.e. length, has a maximum of 32

# commands
# command 1: hello
#   length: 0
#   parameter words: none
#   result codes: success, invalid length
#   purpose: confirm that the bootloader exists and is alive. applications
#            should respond to this command by resetting the system so that the
#            bootloader starts.

# command 2: write data
#   length: 1-max length
#   parameter words: destination address, data to write*length-1
#   result codes: success, invalid length
#   purpose: write words to arbitrary memory address. note that the bootloader
#            lives from 0xFF00 to 0xFFFF, and overwriting it would be bad.

# command 3: jump to code
#   length: 1
#   parameter words: destination address
#   result codes: success, invalid length
#   purpose: jump to given address. register values are undefined after the
#            jump. W points to EXACTLY ONE valid register window. W MUST BE SET
#            EXPLICITLY before any W-relative/adjust instructions are used.

# command 4: read data
#   length: 2
#   parameter words: source address, source length (up to max length)
#   result codes: read result, invalid length
#   purpose: read words from arbitrary memory address.

# results
# result 1: success
#   length: 0
#   parameter words: none
#   purpose: say that everything went great

# result 2: invalid command
#   length: 1
#   parameter words: reason: 0=unknown cmd, 1=invalid length, 2=bad CRC,
#                            3=timeout
#   purpose: say that the command couldn't be processed for whatever reason

# result 3: read result
#   length: 0-max length
#   parameter words: the words
#   purpose: give back the read words

import random

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from .bonetools import *

from ..gateware.periph_map import p_map

# INFO WORDS
# The gateware gets to store seven 16-bit words as information about itself. The
# bootloader gets the 8th to store the version. The PC bootload script verifies
# the bootloader version, then passes the remaining words to the PC application.
BOOTLOADER_VERSION = 1

# MEMORY MAP
# We have a 256 word memory into which we have to fit all the code, buffers, and
# register windows. To ensure the bootloader will always work after a reset,
# only the top 64 words can be written to. To ensure the PC bootload script
# always knows where the info words are, we put them right below the RAM region.
# The memory appears nominally at 0xFF00-0xFFFF, but we omit the leading 0xFF
# from the table below.

# Address | Size | Purpose
# --------+------+--------------------------------
# 0x00-B7 | 184  | (R) Code
# 0xB8-BF | 8    | (R) Info words
# 0xC0-DF | 32   | (RW) Packet buffer
# 0xE0-FF | 32   | (RW) Register windows

FW_MAX_LENGTH = 184
RAM_PACKET_BUFFER = 0xFFC0

def make_bootloader(info_words):

    cleaned_info_words = [int(info_word) & 0xFFFF for info_word in info_words]
    if len(cleaned_info_words) != 7:
        raise ValueError("expected exactly seven info words")
    cleaned_info_words.append(BOOTLOADER_VERSION)

    FW_MAX_LEN = 184


    fw = [
        MOVR(R0, "hi"),
    L("tx_wait"),
        LDXA(R1, p_map.uart.r_tx_status),
        ANDI(R1, R1, 1),
        BZ0("tx_wait"),

        LD(R1, R0, 0),
        CMPI(R1, 0),
        BEQ("done"),
        STXA(R1, p_map.uart.w_tx_lo),
        ADDI(R0, R0, 1),
        J("tx_wait"),

    L("done"),
        J("done"),

    L("hi"),
        list(ord(c) for c in "Hello, world!"),
    ]

    # assemble just the code region
    assembled_fw = Instr.assemble(fw)
    fw_len = len(assembled_fw)
    if len(assembled_fw) > FW_MAX_LENGTH:
        raise ValueError(
            "bootrom length {} is over max of {} by {} words".format(
                fw_len, FW_MAX_LENGTH, fw_len-FW_MAX_LENGTH))
    elif True:
        print("bootrom length {} is under max of {} by {} words".format(
            fw_len, FW_MAX_LENGTH, FW_MAX_LENGTH-fw_len))

    # glue on the info words
    assembled_fw.extend(cleaned_info_words)
    # then the (initially zero) RAM region
    assembled_fw.extend([0]*64)

    return assembled_fw
