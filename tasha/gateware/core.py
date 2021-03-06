# the core of this whole deal. contains the main CPU and the peripheral hookups.
from nmigen import *
from nmigen.asserts import Past, Rose, Fell

# boneless CPU architecture stuff
from boneless.gateware import ALSRU_4LUT, CoreFSM
from boneless.arch.opcode import Instr
from boneless.arch.opcode import *

from . import reset_req, uart, timer, snes
from .periph_map import p_map
from .bootloader_fw import make_bootloader

class TASHACore(Elaboratable):
    def __init__(self, snes_signals, uart_signals, memory_signals):
        self.snes_signals = snes_signals
        self.uart_signals = uart_signals
        self.memory_signals = memory_signals

        self.o_reset_req = Signal() # request a full system reset, active high

        # compile the bootloader first. we have a bootloader so a) the code can
        # be updated without having to reconfigure the FPGA and b) because the
        # main RAM can't always be loaded from configuration anyway.

        # we can store seven info words that the PC bootload script will read
        # and give to the PC application. eventually we may do some sort of
        # capability list, but for now it's empty. 
        self.bootrom_data = make_bootloader([0]*4)

        # the main CPU. configured to start in the boot ROM.
        self.cpu_core = CoreFSM(alsru_cls=ALSRU_4LUT,
            reset_pc=0xFF00, reset_w=0xFFF8)
        # the boot ROM, which holds the bootloader (and its RAM).
        self.bootrom = Memory(width=16, depth=256, init=self.bootrom_data)

        # the reset request peripheral. this lets us get the system into a clean
        # state from a remote command or similar
        self.reset_req = reset_req.ResetReq()

        # the UART peripheral. it runs at a fixed 2 megabaud so we can stream
        # ultra fast TASes in without a problem.
        self.uart = uart.SysUART(divisor=uart.calculate_divisor(12e6, 2000000))

        # the (very simple) timers. used for various housekeeping things
        self.timer = timer.Timer()

        # the SNES communication peripheral. emulates the controllers and drives
        # the APU clock
        self.snes = snes.SNES(self.snes_signals)

    def elaborate(self, platform):
        m = Module()
        m.submodules.cpu_core = cpu_core = self.cpu_core
        m.submodules.bootrom_r = bootrom_r = self.bootrom.read_port(
            transparent=False)
        m.submodules.bootrom_w = bootrom_w = self.bootrom.write_port()

        m.submodules.reset_req = reset_req = self.reset_req
        m.submodules.uart = uart = self.uart
        m.submodules.timer = timer = self.timer
        m.submodules.snes = snes = self.snes

        # hook up main bus. the main RAM gets the first half and the boot ROM
        # gets the second (though nominally, it's from 0xFF00 to 0xFFFF)
        mainram_en = Signal()
        bootrom_en = Signal()
        # the code area of the boot ROM can't be written to to avoid destroying
        # it by accident. if it got destroyed, then the bootloader wouldn't work
        # after reset; a full reconfiguration would be required.
        bootrom_writable = Signal()
        m.d.comb += [
            mainram_en.eq(cpu_core.o_bus_addr[-1] == 0),
            bootrom_en.eq(cpu_core.o_bus_addr[-1] == 1),
            bootrom_writable.eq((cpu_core.o_bus_addr & 0xC0) == 0xC0)
        ]
        # wire the main bus to the memories
        m.d.comb += [
            # address bus
            bootrom_r.addr.eq(cpu_core.o_bus_addr),
            bootrom_w.addr.eq(cpu_core.o_bus_addr),
            self.memory_signals.o_addr.eq(cpu_core.o_bus_addr),
            # write data
            bootrom_w.data.eq(cpu_core.o_mem_data),
            self.memory_signals.o_wdata.eq(cpu_core.o_mem_data),
            # enables
            bootrom_r.en.eq(bootrom_en & cpu_core.o_mem_re),
            bootrom_w.en.eq(bootrom_en & cpu_core.o_mem_we & bootrom_writable),
            self.memory_signals.o_re.eq(mainram_en & cpu_core.o_mem_re),
            self.memory_signals.o_we.eq(mainram_en & cpu_core.o_mem_we),
        ]
        # mux read results back to the cpu bus. the cpu gets the read value if
        # it addressed the memory last cycle. it can only address one memory at
        # a time (if it did more then all the results would be ORed together).
        mainram_rdata = Signal(16)
        bootrom_rdata = Signal(16)
        m.d.comb += [
            mainram_rdata.eq(Mux(Past(mainram_en),
                self.memory_signals.i_rdata, 0)),
            bootrom_rdata.eq(Mux(Past(bootrom_en), bootrom_r.data, 0)),

            cpu_core.i_mem_data.eq(mainram_rdata | bootrom_rdata),
        ]
        # the main RAM runs with the system clock
        m.d.comb += [
            self.memory_signals.o_clock.eq(ClockSignal("sync")),
            self.memory_signals.o_reset.eq(ResetSignal("sync")),
        ]

        # split up the external bus into (at most) 16 regions of 16 registers.
        # we use the first 128 words and last 128 words of the bus since those
        # regions can be addressed with the 1-word form of the external bus
        # instructions. each peripheral gets 1 read and 1 write enable bit, 4
        # address bits, 16 write data bits, and gives back 16 read data bits
        NUM_PERIPHS = 4
        periph_en = tuple(Signal(1) for _ in range(NUM_PERIPHS))
        periph_re = tuple(Signal(1) for _ in range(NUM_PERIPHS))
        periph_we = tuple(Signal(1) for _ in range(NUM_PERIPHS))
        periph_addr = Signal(4)
        periph_wdata = Signal(16)
        periph_rdata = tuple(Signal(16) for _ in range(NUM_PERIPHS))

        m.d.comb += periph_addr.eq(cpu_core.o_bus_addr[:4])
        m.d.comb += periph_wdata.eq(cpu_core.o_ext_data)
        # hook up enable bits
        x_addr = cpu_core.o_bus_addr
        for pi in range(NUM_PERIPHS):
            m.d.comb += [
                periph_en[pi].eq(
                    (x_addr[-1] == (pi >> 3)) & (x_addr[4:7] == (pi & 7))),

                periph_re[pi].eq(cpu_core.o_ext_re & periph_en[pi]),
                periph_we[pi].eq(cpu_core.o_ext_we & periph_en[pi]),
            ]

        # mux peripheral read data back to the CPU
        result_expr = Const(0, 16)
        for pi in range(NUM_PERIPHS):
            # this peripheral gets to put its result on the bus if it was
            # addressed last cycle
            result_expr = result_expr | \
                Mux(Past(periph_en[pi]), periph_rdata[pi], 0)
        m.d.comb += cpu_core.i_ext_data.eq(result_expr)

        # hook up the reset request peripheral
        m.d.comb += [
            reset_req.i_re.eq(periph_re[p_map.reset_req.periph_num]),
            reset_req.i_we.eq(periph_we[p_map.reset_req.periph_num]),
            reset_req.i_addr.eq(periph_addr),
            reset_req.i_wdata.eq(periph_wdata),
            periph_rdata[p_map.reset_req.periph_num].eq(reset_req.o_rdata),

            self.o_reset_req.eq(reset_req.o_reset_req),
        ]

        # hook up the UART
        m.d.comb += [
            uart.i_re.eq(periph_re[p_map.uart.periph_num]),
            uart.i_we.eq(periph_we[p_map.uart.periph_num]),
            uart.i_addr.eq(periph_addr),
            uart.i_wdata.eq(periph_wdata),
            periph_rdata[p_map.uart.periph_num].eq(uart.o_rdata),

            uart.i_rx.eq(self.uart_signals.i_rx),
            self.uart_signals.o_tx.eq(uart.o_tx),
        ]

        # hook up the timers
        m.d.comb += [
            timer.i_re.eq(periph_re[p_map.timer.periph_num]),
            timer.i_we.eq(periph_we[p_map.timer.periph_num]),
            timer.i_addr.eq(periph_addr),
            timer.i_wdata.eq(periph_wdata),
            periph_rdata[p_map.timer.periph_num].eq(timer.o_rdata),
        ]

        # hook up the SNES interface
        m.d.comb += [
            snes.i_re.eq(periph_re[p_map.snes.periph_num]),
            snes.i_we.eq(periph_we[p_map.snes.periph_num]),
            snes.i_addr.eq(periph_addr),
            snes.i_wdata.eq(periph_wdata),
            periph_rdata[p_map.snes.periph_num].eq(snes.o_rdata),
        ]

        return m
