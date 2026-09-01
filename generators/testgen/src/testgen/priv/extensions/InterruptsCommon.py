##################################
# priv/extensions/InterruptsCommon.py
#
# Shared building blocks for the Interrupts* privileged suites.
# David_Harris@hmc.edu 29 August 2026
# SPDX-License-Identifier: Apache-2.0
##################################

"""Shared building blocks for the Interrupts* privileged suites.

Every testcase has the same shape: configure the interrupt state from the suite's
home mode, hop to the mode under test, raise one interrupt with the RVTEST_SET_*_INT
macro for that mode, idle, leave a coverage sample point, record how many traps were
taken, hop home and clear everything. The trap handler records each interrupt in the
signature and clears its source, so tests never need per-interrupt cleanup logic.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from testgen.asm.helpers import write_sigupd
from testgen.asm.interrupts import set_mtimer_int_soon
from testgen.asm.tsbi import tsbi_call
from testgen.data.state import TestData


@dataclass(frozen=True)
class Interrupt:
    name: str  # coverpoint/bin name, e.g. MTI
    cause: int  # xcause exception code
    level: str  # privilege level the interrupt belongs to: M, S (or VS later)
    macro: str  # RVTEST_SET_<macro>_INT_<mode> / RVTEST_CLR_<macro>_INT_<mode>


INTERRUPTS: tuple[Interrupt, ...] = (
    Interrupt("LCOFI", 13, "S", "LCOF"),
    Interrupt("MTI", 7, "M", "MTIME"),
    Interrupt("MSI", 3, "M", "MSW"),
    Interrupt("MEI", 11, "M", "MEXT"),
    Interrupt("STI", 5, "S", "STIME"),
    Interrupt("SSI", 1, "S", "SSW"),
    Interrupt("SEI", 9, "S", "SEXT"),
    # VS-level interrupts (VSSI 2, VSTI 6, VSEI 10) are added once VS/VU modes are supported.
)
INTERRUPT_BY_NAME = {i.name: i for i in INTERRUPTS}
M_INTERRUPTS = tuple(i for i in INTERRUPTS if i.level == "M")
S_INTERRUPTS = tuple(i for i in INTERRUPTS if i.level == "S")

GOTO = {"M": "RVTEST_TSBI_GOTO_MMODE", "S": "RVTEST_TSBI_GOTO_SMODE", "U": "RVTEST_TSBI_GOTO_UMODE"}
MODE_CONDITION = {"M": None, "S": "defined(S_SUPPORTED)", "U": "defined(U_SUPPORTED)"}
TVEC_CSR = {"M": "mtvec", "S": "stvec", "U": "stvec"}

# The coverage model samples interrupt state at this instruction; an interrupt that stays
# pending (masked or not delegated to the current mode) is observed here.
COVERAGE_MARK = [
    ".option push",
    ".option norvc",
    "addi x0, x0, 1  # coverage sample point for an interrupt that stays pending",
    ".option pop",
]


def interrupt_pairs(interrupts: tuple[Interrupt, ...] = INTERRUPTS) -> list[tuple[Interrupt, Interrupt]]:
    """Every unordered pair of interrupts, in cause order."""
    ordered = sorted(interrupts, key=lambda i: i.cause)
    return [(a, b) for k, a in enumerate(ordered) for b in ordered[k + 1 :]]


def raise_order(interrupts: tuple[Interrupt, ...]) -> list[Interrupt]:
    """Order in which several interrupts are raised: CSR/CLINT sources first, then the external ones with
    the supervisor one before the machine one. A PLIC that feeds both contexts from one source only raises
    the context enabled first, and a later mip write can drop an APLIC-driven SEIP on some models."""
    return sorted(interrupts, key=lambda i: (i.macro.endswith("EXT"), i.cause))


def raise_condition(intr: Interrupt, extra: dict[str, str] | None = None) -> str:
    cond = supported_condition(intr)
    if extra and intr.name in extra:
        cond = f"{cond} && {extra[intr.name]}"
    return cond


def raise_all(priv: str, interrupts: list[Interrupt], extra: dict[str, str] | None = None) -> list[str]:
    """Raise every interrupt in interrupts from mode priv, each under its own preprocessor condition."""
    lines = []
    for intr in interrupts:
        lines.extend([f"#if {raise_condition(intr, extra)}", set_int(intr, priv), "#endif"])
    return lines


def wait_pending(
    priv: str, interrupts: list[Interrupt], r_val: int, r_mask: int, extra: dict[str, str] | None = None
) -> list[str]:
    """Spin until every interrupt in interrupts is pending in mip (read through T-SBI below M-mode)."""
    read = [f"csrr x{r_val}, mip"] if priv == "M" else [tsbi_call(f"csrr x{r_val}, mip")]
    lines = ["# Wait until every raised source is pending (external interrupts may take a while)", f"LI(x{r_mask}, 0)"]
    for intr in interrupts:
        lines.extend(
            [
                f"#if {raise_condition(intr, extra)}",
                f"LI(x{r_val}, 1 << {intr.cause})",
                f"or x{r_mask}, x{r_mask}, x{r_val}",
                "#endif",
            ]
        )
    return [*lines, "1:", *read, f"and x{r_val}, x{r_val}, x{r_mask}", f"bne x{r_val}, x{r_mask}, 1b"]


def write_xie(priv: str, csr: str, r_temp: int, value: int | str) -> list[str]:
    """csr (mie or sie) = value from mode priv; mie goes through T-SBI below M-mode."""
    lines = [f"LI(x{r_temp}, {value})"]
    if priv == "M" or (priv == "S" and csr == "sie"):
        lines.append(f"csrw {csr}, x{r_temp}")
    else:
        lines.append(tsbi_call(f"csrw {csr}, x{r_temp}"))
    return lines


def supported_condition(intr: Interrupt) -> str:
    """Preprocessor condition under which a platform can raise this interrupt."""
    cond = f"defined(UDB_{intr.name}_SUPPORTED)"
    if intr.level == "S":
        cond = f"defined(S_SUPPORTED) && {cond}"
    return cond


def pair_condition(a: Interrupt, b: Interrupt) -> str | None:
    """Preprocessor condition under which two interrupts can be pending together: SEI and MEI cannot on a
    platform whose PLIC feeds both external contexts from one source."""
    if {a.name, b.name} == {"SEI", "MEI"}:
        return "!defined(RVMODEL_SEXT_MEXT_SHARED_SOURCE)"
    return None


def delegation_condition(intr: Interrupt) -> str:
    return f"defined(UDB_{intr.name}_DELEGATION_SUPPORTED)"


def tvec_condition(priv: str, mode: int) -> str:
    return f"defined(UDB_{TVEC_CSR[priv].upper()}_MODES_{mode})"


def preprocessor_if(conditions: Sequence[str | None]) -> list[str]:
    conds = [c for c in conditions if c]
    return [f"#if {' && '.join(conds)}"] if conds else []


def preprocessor_endif(conditions: Sequence[str | None]) -> list[str]:
    return ["#endif"] if any(conditions) else []


def set_int(intr: Interrupt, priv: str) -> str:
    return f"RVTEST_SET_{intr.macro}_INT_{priv}"


def clr_int(intr: Interrupt, priv: str) -> str:
    return f"RVTEST_CLR_{intr.macro}_INT_{priv}"


def disarm_stimecmp(priv: str, r_temp: int) -> list[str]:
    """stimecmp = all ones from mode priv (through T-SBI below M-mode, which is legal even when STCE = 0)."""
    if priv == "M":
        return ["RVTEST_CLR_SSTC_INT_M"]
    return [
        f"LI(x{r_temp}, -1)",
        "#if __riscv_xlen == 32",
        tsbi_call(f"csrw stimecmph, x{r_temp}"),
        "#endif",
        tsbi_call(f"csrw stimecmp, x{r_temp}"),
    ]


def set_stce(priv: str, r_temp: int, stce: int) -> list[str]:
    """menvcfg.STCE = stce from mode priv (through T-SBI below M-mode)."""
    op = "csrs" if stce else "csrc"
    lines = [
        f"# menvcfg.STCE = {stce}",
        "#if __riscv_xlen == 64",
        f"LI(x{r_temp}, 1)",
        f"slli x{r_temp}, x{r_temp}, 63",
    ]
    lines.append(f"{op} menvcfg, x{r_temp}" if priv == "M" else tsbi_call(f"{op} menvcfg, x{r_temp}"))
    lines.extend(["#else", f"LI(x{r_temp}, 0x80000000)"])
    lines.append(f"{op} menvcfgh, x{r_temp}" if priv == "M" else tsbi_call(f"{op} menvcfgh, x{r_temp}"))
    lines.append("#endif")
    return lines


def set_stimecmp_zero(priv: str, direct: bool) -> list[str]:
    """stimecmp = 0 (raises STI when STCE = 1): directly when the mode may access it, else through T-SBI."""
    if direct:
        return [
            "csrw stimecmp, zero",
            "#if __riscv_xlen == 32",
            "csrw stimecmph, zero  # last write arms the comparator",
            "#endif",
        ]
    return [tsbi_call("csrw stimecmp, x0"), "#if __riscv_xlen == 32", tsbi_call("csrw stimecmph, x0"), "#endif"]


def clear_all(priv: str, r_temp: int, interrupts: tuple[Interrupt, ...] = INTERRUPTS) -> list[str]:
    """Clear every supported interrupt source from mode priv."""
    lines = ["# Clear every supported interrupt source"]
    for intr in interrupts:
        lines.extend([f"#if {supported_condition(intr)}", clr_int(intr, priv), "#endif"])
    lines.extend(["#if defined(S_SUPPORTED) && defined(SSTC_SUPPORTED)", *disarm_stimecmp(priv, r_temp), "#endif"])
    return lines


def set_tvec_mode(priv: str, mode: int) -> list[str]:
    csr = TVEC_CSR[priv]
    return [f"# {csr}.MODE = {mode} ({'vectored' if mode else 'direct'})", f"csrci {csr}, 3", f"csrsi {csr}, {mode}"]


def restore_tvec_mode(priv: str) -> list[str]:
    csr = TVEC_CSR[priv]
    return [
        f"#ifdef UDB_{csr.upper()}_MODES_0",
        f"csrci {csr}, 3  # restore {csr}.MODE to the boot value (direct)",
        "#endif",
    ]


def goto(priv: str) -> list[str]:
    return [GOTO[priv]]


def read_pending(intr: Interrupt, priv: str, r_val: int, r_mask: int) -> list[str]:
    """Read the pending bit of intr as seen from mode priv into r_val (mip in M, sip in S, sip via T-SBI in U)."""
    if priv == "M":
        read = [f"csrr x{r_val}, mip"]
    elif priv == "S" and intr.level == "S":
        read = [f"csrr x{r_val}, sip"]
    else:
        read = [tsbi_call(f"csrr x{r_val}, {'sip' if intr.level == 'S' else 'mip'}")]
    return [*read, f"LI(x{r_mask}, 1 << {intr.cause})", f"and x{r_val}, x{r_val}, x{r_mask}  # {intr.name} pending?"]


def set_pending_csr(intr: Interrupt, priv: str, csr: str, r_mask: int) -> list[str]:
    """Raise intr from mode priv by setting its bit in csr (mip or sip); T-SBI is used where priv cannot access csr."""
    if priv == "M" or (priv == "S" and csr == "sip"):
        write = f"csrs {csr}, x{r_mask}"
    else:
        write = tsbi_call(f"csrs {csr}, x{r_mask}")
    return [f"LI(x{r_mask}, 1 << {intr.cause})", write]


def read_trap_count(reg: int) -> list[str]:
    return [f"LA(x{reg}, rvtest_trap_count)", f"LREG x{reg}, 0(x{reg})"]


def set_tw(priv: str, r_temp: int, tw: int) -> list[str]:
    """mstatus.TW = tw from mode priv (through T-SBI below M-mode)."""
    op = "csrs" if tw else "csrc"
    return [
        f"LI(x{r_temp}, 0x200000)",
        f"{op} mstatus, x{r_temp}" if priv == "M" else tsbi_call(f"{op} mstatus, x{r_temp}"),
    ]


def arm_mtimer_soon_m(regs: list[int], mult: int) -> list[str]:
    """mtimecmp = mtime + RVMODEL_TIMER_INT_SOON_DELAY * mult, written directly from M-mode (regs: 6 scratch)."""
    return set_mtimer_int_soon(*regs, delay=f"(RVMODEL_TIMER_INT_SOON_DELAY * {mult})")


def arm_stimecmp_soon_s(r_lo: int, r_hi: int, r_delay: int, mult: int) -> list[str]:
    """stimecmp = mtime + RVMODEL_TIMER_INT_SOON_DELAY * mult from S-mode: mtime is read through T-SBI,
    stimecmp is written directly (menvcfg.STCE = 1)."""
    return [
        "#ifdef RVMODEL_MTIME_ADDRESS",
        f"LI(x{r_delay}, -1)",
        "#if __riscv_xlen == 32",
        f"csrw stimecmph, x{r_delay}  # disarm while the comparator is rewritten",
        "#endif",
        f"csrw stimecmp, x{r_delay}",
        f"LA(x{r_lo}, RVMODEL_MTIME_ADDRESS)",
        "#if __riscv_xlen == 64",
        tsbi_call(f"ld x{r_lo}, 0(x{r_lo})"),
        f"LI(x{r_delay}, (RVMODEL_TIMER_INT_SOON_DELAY * {mult}))",
        f"add x{r_lo}, x{r_lo}, x{r_delay}",
        f"csrw stimecmp, x{r_lo}",
        "#else",
        f"mv x{r_hi}, x{r_lo}",
        tsbi_call(f"lw x{r_hi}, 4(x{r_hi})"),
        tsbi_call(f"lw x{r_lo}, 0(x{r_lo})"),
        f"LI(x{r_delay}, (RVMODEL_TIMER_INT_SOON_DELAY * {mult}))",
        f"add x{r_delay}, x{r_lo}, x{r_delay}  # low word of the comparand",
        f"sltu x{r_lo}, x{r_delay}, x{r_lo}  # carry",
        f"add x{r_hi}, x{r_hi}, x{r_lo}",
        f"csrw stimecmph, x{r_hi}",
        f"csrw stimecmp, x{r_delay}",
        "#endif",
        "#endif",
    ]


def wfi_until_timer(r_before: int, r_val: int, pending_bit: int | None, pending_csr: str = "mip") -> list[str]:
    """Repeat WFI until the (already armed) timer interrupt has fired.

    r_before holds the trap count read in the current mode after the timer was armed. The loop leaves
    on any trap; with pending_bit (the mode cannot take the interrupt) it leaves once that bit of
    pending_csr is pending.
    """
    lines = ["1:", "wfi", *read_trap_count(r_val), f"bne x{r_val}, x{r_before}, 2f  # a trap was taken"]
    if pending_bit is not None:
        lines.extend(
            [
                f"csrr x{r_val}, {pending_csr}",
                f"andi x{r_val}, x{r_val}, {1 << pending_bit}",
                f"bnez x{r_val}, 2f  # pending without a trap",
            ]
        )
    lines.extend(["j 1b", "2:"])
    return lines


def read_pending_mask(priv: str, r_val: int, r_mask: int, interrupts: list[Interrupt]) -> list[str]:
    """Read the pending bits of interrupts as seen from mode priv into r_val."""
    if priv == "M":
        read = [f"csrr x{r_val}, mip"]
    elif priv == "S":
        read = [f"csrr x{r_val}, sip"]
    else:
        read = [tsbi_call(f"csrr x{r_val}, sip")]
    mask = 0
    for intr in interrupts:
        mask |= 1 << intr.cause
    return [*read, f"LI(x{r_mask}, {mask:#x})", f"and x{r_val}, x{r_val}, x{r_mask}  # still pending?"]


def trigger_and_record(
    test_data: TestData, intr: Interrupt, priv: str, r_val: int, r_mask: int, set_lines: list[str] | None = None
) -> list[str]:
    """Raise intr from mode priv (by macro, or by set_lines), wait, then record whether it is still pending.

    A taken interrupt is recorded by the trap handler; an interrupt that stays pending shows up here.
    """
    return [
        *(set_lines if set_lines is not None else [set_int(intr, priv)]),
        f"RVTEST_IDLE_FOR_INTERRUPT(x{r_val})",
        *COVERAGE_MARK,
        *read_pending(intr, priv, r_val, r_mask),
        write_sigupd(r_val, test_data),
    ]
