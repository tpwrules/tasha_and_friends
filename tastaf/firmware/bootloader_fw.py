# firmware for the system bootloader

import random

from boneless.arch.opcode import Instr
from boneless.arch.opcode import *
from .bonetools import *

from ..gateware.periph_map import p_map

def make_bootloader(info_words):
    delay_ms = 5000
    delay = int((12e6*(delay_ms/1e3))//(4*3))
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
        list(ord(c) for c in "Hello, world!")
    ]

    assembled_fw = Instr.assemble(fw)

    return assembled_fw, len(assembled_fw)
