# firmware for the system bootloader. its only job is to (quickly) receive a
# program over the UART and start it. FTDI chips impose a 16ms latency on device
# -> host transmissions, so this protocol is designed to do data transfer in one
# continuous stream and so eliminate the host having to wait for the device.

# notational notes:
# boneless is a word-based architecture, it has no concept of the 8 bit byte.
# but we do, so we have to define what a word means.
# * a "word" is a 16 bit unsigned integer, transmitted and stored in
#   little-endian byte order.
# * an "address" selects one "word".

# we define "CRC" as CRC-16/KERMIT (as defined by anycrc). it's computed in
# little-endian order, such that the CRC of words [0x0102, 0x0304] equals the 
# CRC of bytes [0x2, 0x1, 0x3, 0x4]

# UART command packet format:
# first word: header (always 0x7A5A)
# second word: command
#   bits 7-0: number of parameters, always 2 for the bootloader's commands
#   bits 15-8: command number, defined later
# third word: parameter 1 (command specific)
# fourth word: parameter 2 (command specific)
# fifth word: CRC of previous words (except first)

# UART response packet format: (in response to command)
# first word: header (always 0x7A5A)
# second word: result
#   bits 7-0: number of parameters, always 1 for the bootloader's responses
#   bits 15-8: result code, always 1 for the bootloader's responses
# third word: command status:
#              0=unknown cmd/invalid length, 1=bad CRC,
#              2=RX error/timeout, 3=success
# fourth word: CRC of previous words (except first)

# commands
# command 1: hello
#   parameter 1: unused
#   parameter 2: unused
#   purpose: confirm that the bootloader exists and is alive. always responds
#            with success (unless the command packet was bad). applications
#            should respond to this command by resetting the system so that the
#            bootloader starts. (and not send out a success response)

# command 2: write data
#   parameter 1: destination address
#   parameter 2: data length
#   purpose: write words to arbitrary memory addresses. note that the bootloader
#            lives from 0xFF00 to 0xFFFF, and overwriting it would be bad.
#
#            once the command packet is received and validated, the bootloader
#            will send a success response packet. it then expects "length" words
#            to follow, followed by a CRC of those words. once processed, it
#            will send out a second response packet with error or success. if
#            the second response contains an error, the contents of the written
#            memory is UNPREDICTABLE.

# command 3: jump to code
#   parameter 1: execution address
#   parameter 2: unused
#   purpose: jump to given address. responds with success before the jump
#            (unless the command packet was bad). register values are undefined
#            after the jump. W points to EXACTLY ONE valid register window. W
#            MUST BE SET EXPLICITLY before any W-relative/adjust instructions
#            are used.

# command 4: read data
#   parameter 1: source address
#   parameter 2: data length
#   purpose: read words from arbitrary memory addresses.
#
#            once the command packet is received and validated, the bootloader
#            will send a success response packet. it will then send the "length"
#            words, followed by a CRC of those words. once finished, it will
#            send out a second successful response packet.

import random

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from ..firmware.bonetools import *

from .periph_map import p_map

# INFO WORDS
# The gateware gets to store four 16-bit words as information about itself. The
# bootloader gets the rest to store the version. The host verifies the
# bootloader version and gives the rest of the info words to the host
# application.
BOOTLOADER_VERSION = 3

# very, very temporary. will eventually be automatically detected and managed
# somehow
GATEWARE_VERSION = 1


# MEMORY MAP
# We have a 256 word memory into which we have to fit all the code, buffers, and
# register windows. To ensure the bootloader will always work after a reset,
# only the top 64 words can be written to. To ensure the host always knows where
# the info words are, we put them right below the RAM region. The memory appears
# nominally at 0xFF00-0xFFFF, but we omit the leading 0xFF from the table below.

# Address | Size | Purpose
# --------+------+--------------------------------
# 0x00-B7 | 184  | (R) Code
# 0xB8-BF | 8    | (R) Info words
# 0xC0-DF | 32   | (RW) Packet buffer
# 0xE0-FF | 32   | (RW) Register windows

FW_MAX_LENGTH = 184
ROM_INFO_WORDS = 0xFFB8
RAM_PACKET_BUFFER = 0xFFC0


def make_bootloader(info_words):
    cleaned_info_words = [int(info_word) & 0xFFFF for info_word in info_words]
    if len(cleaned_info_words) != 4:
        raise ValueError("expected exactly four info words")
    cleaned_info_words.append(0)
    cleaned_info_words.append(0)
    cleaned_info_words.append(GATEWARE_VERSION)
    cleaned_info_words.append(BOOTLOADER_VERSION)

    FW_MAX_LEN = 184

    fw = [
    L("reset"),
        # start from reset. we are always going to start from reset, so we don't
        # have to worry about e.g. changing peripherals back to default modes.

        # set UART receive timeout to about 150ms
        MOVI(R0, int((12e6*(150/1000))/256)),
        STXA(R0, p_map.uart.w_rt_timer),
    ]
    r = RegisterManager(
        "R7:lr R6:comm_word R5:temp R4:cmd_status "
        "R2:param2 R1:param1 R0:command")
    fw.append([
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

        # receive the four packet words
        JAL(r.lr, "rx_word"),
        MOV(r.command, r.comm_word),
        JAL(r.lr, "rx_word"),
        MOV(r.param1, r.comm_word),
        JAL(r.lr, "rx_word"),
        MOV(r.param2, r.comm_word),
        JAL(r.lr, "rx_word"),
        # if the current CRC is x, then CRC(x) = 0, always. we use to reset the
        # CRC to 0 when we are done sending or receiving.
        # so, we've received all the data words and the CRC. if everything went
        # okay, the CRC should now be 0.
        LDXA(r.temp, p_map.uart.r_crc_value),
        AND(r.temp, r.temp, r.temp),
        BZ("crc_ok"),

        # aw heck, it didn't go okay. send the appropriate error.
        MOVI(r.cmd_status, 1),
        J("send_final_response_packet"),

    L("crc_ok"),
        # now we need to figure out the command.
        # the low 8 bits are the length, which is always 2.
        SUBI(r.command, r.command, 2),
        # the high 8 bits are the command number, starting from 1
        MOVI(r.temp, 0x100),
        # assume the handler wants to say success
        MOVI(r.cmd_status, 3),

        SUB(r.command, r.command, r.temp), # command 1
        # hello command: we just need to transmit a success packet back, and the
        # status is already set accordingly
        BEQ("send_final_response_packet"), 
        SUB(r.command, r.command, r.temp), # command 2
        BEQ("sys_cmd_write_data"),
        SUB(r.command, r.command, r.temp), # command 3
        BEQ("sys_cmd_jump_to_code"),
        SUB(r.command, r.command, r.temp), # command 4
        BEQ("sys_cmd_read_data"),

        # if the command is unknown or the length is wrong, none of the above
        # will have matched. send the appropriate error.
        MOVI(r.cmd_status, 0),
        # fall through
    ])
    r -= "command"

    r += "R0:send_lr"
    fw.append([
    L("send_final_response_packet"),
        # return to main loop
        MOVR(r.lr, "main_loop"),
    L("send_response_packet"),
        # save LR because we need to reuse it to call the tx function
        MOV(r.send_lr, r.lr),
        # send out the header first
        MOVI(r.comm_word, 0x7A5A),
        JAL(r.lr, "tx_word"),
        # reset CRC so the packet CRC is calculated correctly
        STXA(r.send_lr, p_map.uart.w_crc_reset), # we can write anything
        # the command is always the same: length 1 type 1
        MOVI(r.comm_word, 0x0101),
        JAL(r.lr, "tx_word"),
        # then the status code
        MOV(r.comm_word, r.cmd_status),
        JAL(r.lr, "tx_word"),
        # last is the CRC, but the CRC of the last byte is still being
        # calculated right now. reading it this instruction gives garbage.
        MOV(r.lr, r.send_lr), # so prepare to return to our caller
        # now we can read and send it (and sending it resets the CRC to 0)
        LDXA(r.comm_word, p_map.uart.r_crc_value),
        # tx_word will return back to our caller in r.lr
        J("tx_word"),
    ])
    r -= "send_lr param2 param1"

    r += "R2:length R1:dest_addr"
    # generate random prefix so that we effectively can make local labels
    lp = "_{}_".format(random.randrange(2**32))
    fw.append([
    L("sys_cmd_write_data"),
        # transmit back a success packet. the status is already set correctly.
        JAL(r.lr, "send_response_packet"),
        # if the length is 0, we are already done. send the second response.
        AND(r.length, r.length, r.length),
        BZ("send_final_response_packet"),
    L(lp+"write"),
        JAL(r.lr, "rx_word"),
        ST(r.comm_word, r.dest_addr, 0),
        ADDI(r.dest_addr, r.dest_addr, 1),
        SUBI(r.length, r.length, 1),
        BNZ(lp+"write"),
        # receive the CRC too
        JAL(r.lr, "rx_word"),
        # now, if everything was correct, the CRC in the UART will be zero
        LDXA(r.temp, p_map.uart.r_crc_value),
        AND(r.temp, r.temp, r.temp),
        BZ("send_final_response_packet"), # it was! (status already = success)
        # it wasn't. send the appropriate error
        MOVI(r.cmd_status, 1),
        J("send_final_response_packet"),
    ])
    r -= "length dest_addr"

    r += "R2:param2 R1:code_addr"
    fw.append([
    L("sys_cmd_jump_to_code"),
        # transmit back a success packet. the status is already set correctly.
        JAL(r.lr, "send_response_packet"),
        # then jump to the code and let it do its thing
        JR(r.code_addr, 0),
    ])
    r -= "param2 code_addr"

    r += "R2:length R1:source_addr"
    lp = "_{}_".format(random.randrange(2**32))
    fw.append([
    L("sys_cmd_read_data"),
        # transmit back a success packet. the status is already set correctly.
        JAL(r.lr, "send_response_packet"),
        # if the length is 0, we are already done. send the second response
        AND(r.length, r.length, r.length),
        BZ("send_final_response_packet"),
    L(lp+"read"),
        LD(r.comm_word, r.source_addr, 0),
        JAL(r.lr, "tx_word"),
        ADDI(r.source_addr, r.source_addr, 1),
        SUBI(r.length, r.length, 1),
        BNZ(lp+"read"),
        # send the CRC too (which resets the CRC to 0)
        LDXA(r.comm_word, p_map.uart.r_crc_value),
        JAL(r.lr, "tx_word"),
        # send the final success packet (status is already set)
        J("send_final_response_packet"),
    ])
    r -= "length source_addr"
    
    lp = "_{}_".format(random.randrange(2**32))
    fw.append([
    L("rx_word"),
        # check for UART errors (timeouts, overflows, etc.)
        LDXA(r.temp, p_map.uart.r_error),
        AND(r.temp, r.temp, r.temp), # set flags
        BZ0(lp+"error"),
        # check if we have a new byte
        LDXA(r.temp, p_map.uart.r_rx_lo),
        ROLI(r.temp, r.temp, 1),
        BS1("rx_word"),
        # we have the low byte in temp
    L(lp+"rx_hi"),
        # check again for UART errors
        LDXA(r.comm_word, p_map.uart.r_error),
        AND(r.comm_word, r.comm_word, r.comm_word),
        BZ0(lp+"error"),
        # and see if we have the high byte yet
        LDXA(r.comm_word, p_map.uart.r_rx_hi),
        ADD(r.comm_word, r.comm_word, r.comm_word),
        BC1(lp+"rx_hi"),
        # put the bytes together
        OR(r.comm_word, r.comm_word, r.temp),
        # and we are done
        JR(r.lr, 0),
    L(lp+"error"),
        # load RX error status code
        MOVI(r.cmd_status, 2),
        # and send the error packet (it will return to the main loop)
        J("send_final_response_packet"),
    ])
    
    lp = "_{}_".format(random.randrange(2**32))
    fw.append([
    L("tx_word"),
        # wait for buffer space
        LDXA(r.temp, p_map.uart.r_tx_status),
        ANDI(r.temp, r.temp, 1),
        BZ0("tx_word"),
        # then send the low byte
        STXA(r.comm_word, p_map.uart.w_tx_lo),
        # and repeat for the high byte
    L(lp+"tx_hi"),
        LDXA(r.temp, p_map.uart.r_tx_status),
        ANDI(r.temp, r.temp, 1),
        BZ0(lp+"tx_hi"),
        STXA(r.comm_word, p_map.uart.w_tx_hi),
        # and we're done
        JR(r.lr, 0),
        # WARNING! the CRC is still being calculated, so reading it immediately
        # after this function returns will return garbage
    ])

    # assemble just the code region
    assembled_fw = Instr.assemble(fw)
    fw_len = len(assembled_fw)
    if len(assembled_fw) > FW_MAX_LENGTH:
        raise ValueError(
            "bootrom length {} is over max of {} by {} words".format(
                fw_len, FW_MAX_LENGTH, fw_len-FW_MAX_LENGTH))
    elif False:
        print("bootrom length {} is under max of {} by {} words".format(
            fw_len, FW_MAX_LENGTH, FW_MAX_LENGTH-fw_len))

    # pad the code region out to line up the info words
    assembled_fw.extend([0]*(184-fw_len))

    # glue on the info words
    assembled_fw.extend(cleaned_info_words)
    # then the (initially zero) RAM region
    assembled_fw.extend([0]*64)

    return assembled_fw
