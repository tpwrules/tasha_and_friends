-- for DKC2 US v1.1

script_filename = @@LUA_SCRIPT_FILENAME@@
script_dir = script_filename:match("^(.*[/\\])")

-- first instructions of a wait for NMI loop
-- in dkc2 they are all WAI so there is no end
wait_start_addrs = {0x808652, 0x808c9b, 0x8097ca, 0x809c96, 0x80ab78, 0x80b106,
    0x80b54a, 0x80b6be, 0xb5d00e, 0xb5d23c, 0xb5d447}
-- if there were, these would be the first instruction after those loops
wait_end_addrs = {}
-- first instruction of NMI handler
nmi_addr = 0xf3bd
-- first instruction of reset handler
reset_addr = 0x83f7

out_f = nil

-- are we waiting? where did we start?
currently_waiting = false
wait_frame = 0
wait_hcounter = 0
wait_vcounter = 0

-- how many times has the game accessed the hardware registers?
apu_reads = 0
apu_writes = 0
joy_reads = 0
joy_writes = 0

joy_regs = {0x4218, 0x4219, 0x421A, 0x421B, 0x421C, 0x421D, 0x421E, 0x421F,
    0x4016, 0x4017}
apu_regs = {0x2140, 0x2141, 0x2142, 0x2143}

-- we need to know when latches happened relative to NMI so we can insert
-- frequency adjustments at the appropriate points
function latch_handler()
    local out_str = string.format("l,%d,%d,%d\n",
        movie.currentframe(),
        memory.getregister("vcounter"),
        memory.getregister("hcounter")
    )
    if out_f ~= nil then
        out_f:write(out_str)
    end
end
callback.register("latch", latch_handler)

-- we keep track of APU and joypad hardware registers more for curiousity than
-- any useful purpose
function apu_looked(addr, value) apu_reads = apu_reads + 1 end
function apu_touched(addr, value) apu_writes = apu_writes + 1 end
function joy_looked(addr, value) joy_reads = joy_reads + 1 end
function joy_touched(addr, value) joy_writes = joy_writes + 1 end

-- register the hardware register access. the game can access them through any
-- of 128 different banks, so we have to stick our callbacks at all of them.
for bank=0,0x7F do
    if bank >= 0x40 then bank = bank + 0x40 end
    bank = bank * 0x10000
    for i, apu_reg in ipairs(apu_regs) do
        memory.registerread("BUS", bank+apu_reg, apu_looked)
        memory.registerwrite("BUS", bank+apu_reg, apu_touched)
    end
    for i, joy_reg in ipairs(joy_regs) do
        memory.registerread("BUS", bank+joy_reg, joy_looked)
        memory.registerwrite("BUS", bank+joy_reg, joy_touched)
    end
end

function started_waiting(addr, value)
    if not currently_waiting then
        -- if we're not waiting yet, note that we started here. otherwise, we're
        -- just in the wait loop still.
        wait_frame = movie.currentframe()
        wait_hcounter = memory.getregister("hcounter")
        wait_vcounter = memory.getregister("vcounter")
        currently_waiting = true
    end
end

function ended_waiting(addr, value)
    currently_waiting = false
end

function nmi_fired(addr, value)
    local nmi_frame, nmi_hcounter, nmi_vcounter
    nmi_frame = movie.currentframe()
    nmi_hcounter = memory.getregister("hcounter")
    nmi_vcounter = memory.getregister("vcounter")

    -- if we never ended waiting, then, well, we have now!
    if not currently_waiting then
        wait_frame = nmi_frame
        wait_hcounter = nmi_hcounter
        wait_vcounter = nmi_vcounter
    end

    local out_str = string.format('n,'..string.rep("%d,", 9).."%d\n",
        wait_frame,
        wait_vcounter,
        wait_hcounter,
        nmi_frame,
        nmi_vcounter,
        nmi_hcounter,
        apu_reads,
        apu_writes,
        joy_reads,
        joy_writes
    )
    out_f:write(out_str)

    currently_waiting = false
    apu_reads = 0
    apu_writes = 0
    joy_reads = 0
    joy_writes = 0
end

function measure(out_fname)
    -- register the addresses we were given
    for i, wait_start_addr in ipairs(wait_start_addrs) do
        memory.registerexec("BUS", wait_start_addr, started_waiting)
    end
    for i, wait_end_addr in ipairs(wait_end_addrs) do
        memory.registerexec("BUS", wait_end_addr, ended_waiting)
    end
    memory.registerexec("BUS", nmi_addr, nmi_fired)

    out_f = io.open(script_dir .. "/" .. out_fname, "w")
    out_f:write("hello from measure_emulator.lua v1\n")
    out_f:write(string.format("c,%d,%d\n",
        bsnes.get_cpu_frequency(), bsnes.get_smp_frequency()))
end
