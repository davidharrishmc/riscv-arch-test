##################################
# sail_to_rvvi.py
#
# jcarlin@hmc.edu 9 May 2025
# SPDX-License-Identifier: Apache-2.0
#
# Convert a Sail log file (--trace --trace-ptw) into an RVVI-TEXT trace for the
# riscv-arch-test functional coverage testbench
##################################

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

#                           [STEP]     [MODE]:              0xPC               (0xINSN)           DISASM
INSN_PATTERN = re.compile(r"\[(\d+)\] \[(HS|VS|VU|M|S|U)\]: 0x([0-9a-fA-F]+) \(0x([0-9a-fA-F]+)\) (.*)")
REG_PATTERN = re.compile(r"^([xfv])(\d+) <- 0x([0-9a-fA-F]+)")
CSR_PATTERN = re.compile(r"^CSR \S+ \(0x([0-9a-fA-F]+)\) (<-|->) 0x([0-9a-fA-F]+)")
MEM_PATTERN = re.compile(r"^mem\[([A-Za-z.]+),0x([0-9a-fA-F]+)\] (?:<-|->) 0x([0-9a-fA-F]+)")
# Page-table walks: one "PTW: Step" per PTE read, ending in "PTW: Success" or "PTW: Failed"
PTW_START_PATTERN = re.compile(r"PTW: Start, (?:stage=(\S+), level=\d+, )?vpn=0x([0-9a-fA-F]+), access_type=(\S+),")
PTW_STEP_PATTERN = re.compile(
    r"PTW: Step, (?:stage=(\S+), )?level=(\d+), pte=0x([0-9a-fA-F]+)(?:, pte_addr=0x([0-9a-fA-F]+))?"
)
PTW_END_PATTERN = re.compile(r"PTW: (?:Success|Failed|failed)(?:, .*final_ppn=0x([0-9a-fA-F]+))?")
TRAP_PATTERN = re.compile(r"handling (exc|int)#(.+?) at priv \S+ \| tval=0x([0-9a-fA-F]+)")
XRET_PATTERN = re.compile(r"ret-ing from \S+ to (\S+)")
TLB_FLUSH_PATTERN = re.compile(r"(?:sfence|sinval|hfence|hinval)\.")
SATP_PATTERN = re.compile(r"^CSR satp \(0x180\) (?:<-|->) 0x([0-9a-fA-F]+)")
# Memory operand in the disassembly, such as "0x4(x9)" in "lw x13, 0x4(x9)" or "(x6)" in "amoadd.w x8, x14, (x6)"
MEM_OPERAND_PATTERN = re.compile(r"(-?0x[0-9a-fA-F]+)?\(x(\d+)\)")

MODE_CODE = {"M": 3, "S": 1, "HS": 1, "U": 0, "VS": 1, "VU": 0}
PAGE_TYPE = "KMGTP"
XEPC = (0x341, 0x141, 0x241)

# sip and sie are restricted views of mip and mie through mideleg, and Sail logs only the view that was
# accessed, so the delegated bits of a write to the S view are written back to mip/mie. With H, the VS-level
# and SGEI bits of mip/mie live in hip/hie (and hvip drives the VS-level bits of mip), so those views are
# mirrored the same way. Traps and xRETs log only mstatus, so its sstatus fields are mirrored into sstatus.
# fflags and frm are fields of fcsr, so the three are kept consistent.
SIP, MIP, SIE, MIE, MIDELEG = 0x144, 0x344, 0x104, 0x304, 0x303
HIP, HIE, HVIP = 0x644, 0x604, 0x645
MSTATUS, SSTATUS = 0x300, 0x100
FFLAGS, FRM, FCSR = 0x001, 0x002, 0x003
H_BITS, VS_BITS = 0x1444, 0x444
# SD (bit 63, or 31 on RV32), UXL, SDT, SPELP, MXR, SUM, XS, FS, VS, SPP, UBE, SPIE, SIE
SSTATUS_BITS = 0x8000_0003_818D_E762
VIEW_OF = {SIP: MIP, SIE: MIE, HIP: MIP, HIE: MIE, HVIP: MIP, MSTATUS: SSTATUS}

# In VS-mode and VU-mode, a CSR instruction that names one of these supervisor CSRs (sstatus, sie, stvec, sscratch,
# sepc, scause, stval, sip, siselect, sireg*, stopei, stimecmp(h), satp, stopi) accesses the VS CSR 0x100 above it.
# Sail logs the access under the name the instruction used, so record it under the register it changed. Sail
# already logs trap entries under the VS names.
S_CSRS = (0x100, 0x104, 0x105, *range(0x140, 0x145), *range(0x150, 0x158), 0x15C, 0x14D, 0x15D, 0x180, 0xDB0)
VS_CSR_OF = {s_csr: s_csr + 0x100 for s_csr in S_CSRS}


@dataclass
class Event:
    """One RVVI-TEXT event: a retired instruction or a trap."""

    pc: int
    insn: int
    mode: str
    regs: dict[tuple[str, int], str] = field(default_factory=dict)
    csrs: dict[int, int] = field(default_factory=dict)
    mems: list[str] = field(default_factory=list)
    trap: bool = False


def sailLog2Trace(inputLogFile: Path, outputTraceFile: Path) -> None:
    lines = inputLogFile.read_text().splitlines()
    xlen = 64
    for line in lines:
        if m := INSN_PATTERN.search(line):
            xlen = 4 * len(m.group(3))
            break
    hex_digits = xlen // 4
    pte_bytes = xlen // 8
    # Instruction at each PC, for a trap taken before the instruction executes (an interrupt or a trigger)
    insn_at = {int(m.group(3), 16): int(m.group(4), 16) for line in lines if (m := INSN_PATTERN.search(line))}
    # Page-table accesses: the read logged just before each PTW: Step and an A/D update just after it
    walk_accesses: set[int] = set()
    for i, line in enumerate(lines):
        if (m := PTW_STEP_PATTERN.search(line)) and m.group(4):
            for j in (i - 1, i + 1, i + 2):
                if (
                    0 <= j < len(lines)
                    and (mem := MEM_PATTERN.search(lines[j]))
                    and int(mem.group(2), 16) == int(m.group(4), 16)
                ):
                    walk_accesses.add(j)

    csr_state: dict[int, int] = {}
    xregs = [0] * 32
    tlb: dict[int, tuple[int, int]] = {}  # physical page -> (leaf PTE, level) of the walk that mapped it
    tlb_va: dict[int, tuple[int, int]] = {}  # virtual page -> (leaf PTE, level), for faults before memory
    translating = False

    def data_translated(ev_mode: str) -> bool:
        """Whether data accesses in ``ev_mode`` are translated; in M-mode only with mstatus.MPRV and MPP != M."""
        mstatus = csr_state.get(MSTATUS, 0)
        return translating and (ev_mode != "M" or (mstatus >> 17 & 1 == 1 and mstatus >> 11 & 3 != 3))

    def mem_record(bus: str, size: int, va: int, pa: int, **kv: str) -> str:
        pairs = " ".join(f"{k} {v}" for k, v in kv.items())
        return f"MEM {bus} {size} 0x{va:x} 0x{pa:x} {len(kv)}" + (f" {pairs}" if pairs else "")

    def view_mask(csr_num: int) -> int:
        """Bits of the mirrored register that a write to ``csr_num`` reaches."""
        if csr_num in (HIP, HIE):
            return H_BITS
        if csr_num == HVIP:
            return VS_BITS
        if csr_num == MSTATUS:
            return SSTATUS_BITS
        return csr_state.get(MIDELEG, 0) & ~H_BITS

    def write_csr(csrs: dict[int, int], csr_num: int, value: int, mode: str) -> None:
        """Record a CSR write and every view of the same state that it changes."""
        csrs[csr_num] = value
        csr_state[csr_num] = value
        if csr_num in (FFLAGS, FRM, FCSR):
            fcsr = csr_state.get(FCSR, 0)
            if csr_num == FFLAGS:
                fcsr = (fcsr & ~0x1F) | (value & 0x1F)
            elif csr_num == FRM:
                fcsr = (fcsr & ~0xE0) | ((value & 0x7) << 5)
            else:
                fcsr = value
            for view, view_val in ((FFLAGS, fcsr & 0x1F), (FRM, (fcsr >> 5) & 0x7), (FCSR, fcsr)):
                csrs[view] = csr_state[view] = view_val
        view = VIEW_OF.get(csr_num)
        if view is not None and not (mode in ("VS", "VU") and csr_num in (SIP, SIE)):
            mask = view_mask(csr_num)
            csrs[view] = csr_state[view] = (csr_state.get(view, 0) & ~mask) | (value & mask)

    def emit(out: TextIO, ev: Event) -> None:
        width = 4 if ev.insn & 3 != 3 else 8
        parts = [f"{'TRAP' if ev.trap else 'RET'} 0x{ev.pc:0{hex_digits}x} 0x{ev.insn:0{width}x}"]
        parts += [f"{kind.upper()} {num} 0x{val}" for (kind, num), val in ev.regs.items()]
        parts += [f"C 0x{num:03x} 0x{val:0{hex_digits}x}" for num, val in sorted(ev.csrs.items())]
        parts += ev.mems
        parts.append(f"MODE 0x{MODE_CODE[ev.mode]:x} VIRT 0x{int(ev.mode in ('VS', 'VU')):x}")
        out.write(" ".join(parts) + "\n")

    with outputTraceFile.open("w") as out:
        out.write(f"VERSION 0 5\nVENDOR sail 0 16\nPARAMS 3 ILEN 32 XLEN {xlen} NHART 1\n")
        event: Event | None = None
        mode = "M"  # mode after the last event
        fetch_mems: list[str] = []  # walk and fetch records logged before the next instruction
        fetch_pas: list[tuple[int, int]] = []  # (physical address, bytes) fetched for the next instruction
        # Walk in progress: (vpn, access type, G-stage only). A G-stage walk of a VS-stage PTE address is logged
        # inside the VS-stage walk, and Sail does not log the end of every walk, so each step is recorded as it
        # is logged.
        walk: tuple[int, str, bool] | None = None
        leaf: tuple[int, int] | None = None  # (PTE, level) of the last VS-stage or single-stage step
        fault_fetch_mems: list[str] = []  # walk records of a fetch that faulted
        walked_pages: set[int] = set()  # virtual pages with a PTE record in the current event
        trap: tuple[str, str, int] | None = None  # (exc or int, cause, tval) of a trap logged after the event
        trap_csrs: dict[int, int] = {}
        vs_csr_access = False
        data_va: int | None = None

        def finish() -> None:
            """Write the event in progress, and the trap logged after it as its own event if it belongs to another
            instruction: an interrupt, a fetch fault or a trigger, whose xepc is not this instruction."""
            nonlocal event, trap, trap_csrs, mode
            epc = next((trap_csrs[c] for c in XEPC if c in trap_csrs), None)
            separate = trap is not None and (event is None or trap[0] == "int" or epc != event.pc)
            if event is not None:
                if trap is not None and not separate:
                    event.trap = True
                    event.csrs.update(trap_csrs)
                emit(out, event)
            if separate and trap is not None:
                _, cause, tval = trap
                fetch_fault = cause.startswith("fetch-")
                pc = epc if epc is not None else 0
                trap_event = Event(pc, 0 if fetch_fault else insn_at.get(pc, 0), mode, csrs=dict(trap_csrs), trap=True)
                if fetch_fault:
                    trap_event.mems = list(fault_fetch_mems)
                    # A fetch that hit Sail's TLB logs no walk; report the PTE of the faulting page from the TLB model
                    walked = {int(r.split()[3], 16) >> 12 for r in fault_fetch_mems if " PTE " in r}
                    if translating and mode != "M" and tval >> 12 not in walked and tval >> 12 in tlb_va:
                        pte, level = tlb_va[tval >> 12]
                        trap_event.mems.append(
                            mem_record("D", pte_bytes, tval, 0, PTE=f"0x{pte:x}", PT=PAGE_TYPE[level])
                        )
                    trap_event.mems.append(mem_record("I", 0, tval, 0, FAULTED="1"))
                emit(out, trap_event)
            fault_fetch_mems.clear()
            event, trap, trap_csrs = None, None, {}

        for line_num, line in enumerate(lines):
            if line_num in walk_accesses:
                continue
            if insn_match := INSN_PATTERN.search(line):
                walk = None  # a walk ends before the next instruction is logged
                finish()
                _, ev_mode, pc_str, insn_str, disasm = insn_match.groups()
                pc, insn = int(pc_str, 16), int(insn_str, 16)
                event = Event(pc, insn, ev_mode)
                mode = ev_mode
                translated = translating and ev_mode != "M"
                event.mems = list(fetch_mems)
                fetch_mems.clear()
                walked_pages.clear()
                walked_pages.update(int(r.split()[3], 16) >> 12 for r in event.mems if " PTE " in r)
                for i, (pa, size) in enumerate(fetch_pas):
                    va = pc + 2 * i if size == 2 else pc
                    if translated and va >> 12 not in walked_pages and pa >> 12 in tlb:
                        pte, level = tlb[pa >> 12]
                        event.mems.append(mem_record("D", pte_bytes, va, 0, PTE=f"0x{pte:x}", PT=PAGE_TYPE[level]))
                    event.mems.append(mem_record("I", size, va, pa))
                fetch_pas.clear()
                if TLB_FLUSH_PATTERN.match(disasm):
                    tlb.clear()
                    tlb_va.clear()
                vs_csr_access = ev_mode in ("VS", "VU") and disasm.startswith("csrr")
                data_va = None
                mnemonic = disasm.partition(" ")[0]
                mem_match = MEM_OPERAND_PATTERN.search(disasm)
                if mem_match and mnemonic != "jalr" and not mnemonic.startswith(("prefetch.", "v")):
                    offset, base = mem_match.groups()
                    data_va = (xregs[int(base)] + int(offset or "0", 16)) & ((1 << xlen) - 1)
                continue

            if m := PTW_START_PATTERN.search(line):
                g_stage = (m.group(1) or "").startswith("G")
                if not g_stage or walk is None:
                    walk = (int(m.group(2), 16), m.group(3), g_stage)
                    leaf = None
                continue
            if (m := PTW_STEP_PATTERN.search(line)) and walk is not None:
                vpn, access, _ = walk
                fetch_walk = "X" in access
                target = fetch_mems if fetch_walk or event is None else event.mems
                va = vpn << 12 if fetch_walk or data_va is None else data_va
                level, pte, pte_addr = int(m.group(2)), int(m.group(3), 16), int(m.group(4) or "0", 16)
                if (m.group(1) or "").startswith("G"):
                    target.append(mem_record("D", pte_bytes, va, pte_addr, GPTE=f"0x{pte:x}", GPT=PAGE_TYPE[level]))
                else:
                    target.append(mem_record("D", pte_bytes, va, pte_addr, PTE=f"0x{pte:x}", PT=PAGE_TYPE[level]))
                    leaf = (pte, level)
                    if not fetch_walk:
                        walked_pages.add(va >> 12)
                continue
            if (m := PTW_END_PATTERN.search(line)) and walk is not None:
                # Sail does not log the end of every walk; the leaf of a successful walk feeds the TLB model
                if "Success" in line and leaf is not None and not line.startswith("PTW: Success, stage=G"):
                    if m.group(1):
                        tlb[int(m.group(1), 16)] = leaf
                    tlb_va[walk[0]] = leaf
                continue

            if m := MEM_PATTERN.search(line):
                kind, pa, val = m.group(1), int(m.group(2), 16), m.group(3)
                size = len(val) // 2
                if kind == "X":
                    fetch_pas.append((pa, size))
                elif event is not None:
                    va = data_va if data_va is not None else pa
                    if data_translated(event.mode) and va >> 12 not in walked_pages and pa >> 12 in tlb:
                        pte, level = tlb[pa >> 12]
                        event.mems.append(mem_record("D", pte_bytes, va, 0, PTE=f"0x{pte:x}", PT=PAGE_TYPE[level]))
                        walked_pages.add(va >> 12)
                    event.mems.append(mem_record("D", size, va, pa))
                continue

            if m := TRAP_PATTERN.search(line):
                kind, cause, tval = m.group(1), m.group(2), int(m.group(3), 16)
                trap = (kind, cause, tval)
                walk = None
                # Fetches logged before the trap belong to the instruction that did not execute
                fault_fetch_mems[:] = fetch_mems
                fetch_mems.clear()
                fetch_pas.clear()
                memory_fault = kind == "exc" and any(k in cause for k in ("access-fault", "page-fault", "misaligned"))
                if memory_fault and not cause.startswith("fetch-") and event is not None:
                    if tval >> 12 not in walked_pages and tval >> 12 in tlb_va and data_translated(event.mode):
                        pte, level = tlb_va[tval >> 12]
                        event.mems.append(mem_record("D", pte_bytes, tval, 0, PTE=f"0x{pte:x}", PT=PAGE_TYPE[level]))
                    event.mems.append(mem_record("D", 0, tval, 0, FAULTED="1"))
                continue
            if m := XRET_PATTERN.search(line):
                mode = m.group(1)
                continue

            if m := CSR_PATTERN.search(line):
                csr_num, direction, value = int(m.group(1), 16), m.group(2), int(m.group(3), 16)
                if satp := SATP_PATTERN.search(line):
                    translating = int(satp.group(1), 16) >> (60 if xlen == 64 else 31) != 0
                if trap is not None:
                    write_csr(trap_csrs, csr_num, value, mode)
                elif event is not None:
                    if vs_csr_access and csr_num in VS_CSR_OF:
                        csr_num = VS_CSR_OF[csr_num]
                    # A read is a change only if the value differs from what the trace last showed
                    if direction == "<-" or csr_state.get(csr_num) != value:
                        write_csr(event.csrs, csr_num, value, event.mode)
                continue
            if (m := REG_PATTERN.search(line)) and event is not None:
                kind, num, value = m.group(1), int(m.group(2)), m.group(3)
                event.regs[(kind, num)] = value
                if kind == "x":
                    xregs[num] = int(value, 16)
        finish()
