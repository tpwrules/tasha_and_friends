script_filename = @@LUA_SCRIPT_FILENAME@@
script_dir = script_filename:match("^(.*[/\\])")

out_f = nil
-- how far along are we?
curr_nmi_num = 0
start_latch_num = 0 -- latch count at the start of the NMI
curr_latch_num = 0

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
    curr_latch_num = curr_latch_num + 1
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

    local out_str = string.format(string.rep("%d,", 11).."%d\n",
        curr_nmi_num,
        start_latch_num,
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
    curr_nmi_num = curr_nmi_num + 1
    start_latch_num = curr_latch_num
end

function measure(addr_fname, out_fname)
    local addr_f, wait_start_addrs, wait_end_addrs, nmi_addr, reset_addr
    -- read and parse the addresses from the given file
    addr_f = io.open(addr_fname, "r");
    wait_start_addrs = {}
    wait_end_addrs = {}
    nmi_addr = nil
    reset_addr = nil
    while true do
        local line = addr_f:read("*line")
        if line == nil then break end

        -- remove comments
        local ci = line:find("#")
        local clean_line = line
        if ci ~= nil then
            clean_line = line:sub(1, ci-1)
        end
        -- and whitespace
        clean_line = clean_line:match("^%s*(.-)%s*$")
        if clean_line == "" then goto continue end

        local addr, kind
        addr, kind = clean_line:match("^([0-9a-fA-F]+)%s*=%s*([a-z_]+)$")
        if addr == nil then
            print("WARNING: invalid line "..line)
            goto continue
        end

        if kind == "nmi" then
            if nmi_addr ~= nil then
                print("WARNING: duplicate NMI (full line: "..line..")")
                goto continue
            end
            nmi_addr = tonumber(addr, 16)
        elseif kind == "reset" then
            if reset_addr ~= nil then
                print("WARNING: duplicate reset (full line: "..line..")")
                goto continue
            end
            reset_addr = tonumber(addr, 16)
        elseif kind == "wait_start" then
            table.insert(wait_start_addrs, tonumber(addr, 16))
        elseif kind == "wait_end" then
            table.insert(wait_end_addrs, tonumber(addr, 16))
        else
            print("WARNING: unknown kind '"..kind.."' (full line: "..line..")")
        end

        ::continue::
    end
    addr_f:close()

    -- register the addresses we were given
    for i, wait_start_addr in ipairs(wait_start_addrs) do
        memory.registerexec("BUS", wait_start_addr, started_waiting)
    end
    for i, wait_end_addr in ipairs(wait_end_addrs) do
        memory.registerexec("BUS", wait_end_addr, ended_waiting)
    end
    memory.registerexec("BUS", nmi_addr, nmi_fired)

    out_f = io.open(script_dir .. "/" .. out_fname, "w")
    out_f:write("hello\n")
    out_f:write(string.format("cpu:%d,smp:%d\n",
        bsnes.get_cpu_frequency(), bsnes.get_smp_frequency()))
    out_f:write("nmi_num,start_latch_num,wait_f,wait_v,wait_h,nmi_f,nmi_v,")
    out_f:write("nmi_h,apu_r,apu_w,joy_r,joy_w\n")
end
