##################################
# priv/extensions/InterruptsS.py
#
# InterruptsS privileged extension test generator.
# David_Harris@hmc.edu 29 August 2026
# SPDX-License-Identifier: Apache-2.0
##################################

"""Supervisor-level interrupt tests. Boots to S-mode (all supervisor interrupts delegated) and runs
testcases in S and U mode without touching M-mode state."""

from testgen.asm.helpers import comment_banner, write_sigupd
from testgen.asm.tsbi import tsbi_call
from testgen.data.state import TestData
from testgen.data.test_chunk import TestChunk
from testgen.priv.extensions.InterruptsCommon import (
    COVERAGE_MARK,
    INTERRUPT_BY_NAME,
    MODE_CONDITION,
    S_INTERRUPTS,
    Interrupt,
    arm_stimecmp_soon_s,
    clear_all,
    goto,
    interrupt_pairs,
    preprocessor_endif,
    preprocessor_if,
    raise_all,
    raise_order,
    read_pending,
    read_pending_mask,
    read_trap_count,
    restore_tvec_mode,
    set_pending_csr,
    set_stce,
    set_stimecmp_zero,
    set_tvec_mode,
    set_tw,
    supported_condition,
    trigger_and_record,
    tvec_condition,
    wait_pending,
    wfi_until_timer,
    write_xie,
)
from testgen.priv.registry import add_priv_test_generator

covergroup = "InterruptsS_cg"
PRIV_MODES = ("S", "U")


def _setup_s(r_temp: int, priv: str, enable: int, tvec: int, sie_value: int | None = None) -> list[str]:
    """S-mode configuration before a testcase that runs in mode priv. sie is all ones unless sie_value is given."""
    return [
        "# Setup (S-mode): disable and clear everything before configuring",
        "csrw sie, zero",
        "csrci sstatus, 2  # sstatus.SIE = 0",
        *clear_all("S", r_temp, S_INTERRUPTS),
        *set_tvec_mode(priv, tvec),
        f"# sie = {'all ones' if sie_value is None else hex(sie_value)}",
        f"LI(x{r_temp}, {-1 if sie_value is None else hex(sie_value)})",
        f"csrw sie, x{r_temp}",
        f"{'csrsi' if enable else 'csrci'} sstatus, 2  # sstatus.SIE = {enable}",
    ]


def _cleanup_s(priv: str, r_temp: int) -> list[str]:
    return [
        "# Cleanup (S-mode)",
        "csrw sie, zero",
        "csrci sstatus, 2",
        *clear_all("S", r_temp, S_INTERRUPTS),
        *restore_tvec_mode(priv),
    ]


def _trigger_case(
    test_data: TestData, coverpoint: str, intr: Interrupt, priv: str, enable: int, tvec: int, csr: str | None = None
) -> list[str]:
    """One testcase: configure in S-mode, hop to priv, raise intr (by macro, or by a csr write), wait, clean up."""
    r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
    conditions = [supported_condition(intr), MODE_CONDITION[priv], tvec_condition(priv, tvec)]
    via = f"_{csr}" if csr else ""
    lines = [
        *preprocessor_if(conditions),
        *_setup_s(r_temp, priv, enable, tvec),
        *(goto(priv) if priv != "S" else []),
        test_data.add_testcase(f"{priv}_{intr.name}{via}_sie_{enable}_tvec_{tvec}", coverpoint, covergroup),
        *trigger_and_record(
            test_data, intr, priv, r_val, r_mask, set_pending_csr(intr, priv, csr, r_mask) if csr else None
        ),
        *(goto("S") if priv != "S" else []),
        *_cleanup_s(priv, r_temp),
        *preprocessor_endif(conditions),
        "",
    ]
    test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _generate_trigger_tests(test_data: TestData) -> list[str]:
    """Raise each supported supervisor-level interrupt from S and U mode.

    sstatus.SIE = {0/1}, sie = 1s, stvec.MODE = {direct, vectored}; mideleg keeps its boot value
    (every supervisor-level interrupt delegated).
    Expectation: pending if supported; trap in S-mode if SIE = 1, always in U-mode.
    """
    coverpoint = "cp_trigger"
    lines = [comment_banner(coverpoint, _generate_trigger_tests.__doc__)]
    for priv in PRIV_MODES:
        for intr in S_INTERRUPTS:
            for enable in (0, 1):
                for tvec in (0, 1):
                    lines.extend(_trigger_case(test_data, coverpoint, intr, priv, enable, tvec))
    return lines


def _generate_trigger_reg_tests(test_data: TestData) -> list[str]:
    """Like cp_trigger, but raise SSI and SEI by writing the pending register instead of the platform macro.

    S-mode writes sip.SSIP directly and mip.SSIP/mip.SEIP through T-SBI; U-mode writes all three through T-SBI.
    """
    coverpoint = "cp_trigger_reg"
    lines = [comment_banner(coverpoint, _generate_trigger_reg_tests.__doc__)]
    ssi, sei = INTERRUPT_BY_NAME["SSI"], INTERRUPT_BY_NAME["SEI"]
    for priv in PRIV_MODES:
        for intr, csr in ((ssi, "sip"), (ssi, "mip"), (sei, "mip")):
            for enable in (0, 1):
                for tvec in (0, 1):
                    lines.extend(_trigger_case(test_data, coverpoint, intr, priv, enable, tvec, csr))
    return lines


def _generate_trigger_sti_sstc_tests(test_data: TestData) -> list[str]:
    """Raise STI through Sstc (stimecmp = 0) from S and U mode with menvcfg.STCE = {0/1} (set through T-SBI).

    sstatus.SIE = {0/1}, sie = 1s. stimecmp is written directly from S-mode when STCE = 1 and through
    T-SBI otherwise.
    Expectation: STI only when STCE = 1; taken in S-mode if SIE = 1, always in U-mode.
    """
    coverpoint = "cp_trigger_sti_sstc"
    sti = INTERRUPT_BY_NAME["STI"]
    lines = [comment_banner(coverpoint, _generate_trigger_sti_sstc_tests.__doc__)]
    for priv in PRIV_MODES:
        for stce in (0, 1):
            for enable in (0, 1):
                r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
                conditions = ["defined(SSTC_SUPPORTED)", supported_condition(sti), MODE_CONDITION[priv]]
                lines.extend(
                    [
                        *preprocessor_if(conditions),
                        *_setup_s(r_temp, priv, enable, 0),
                        *set_stce("S", r_temp, stce),
                        *(goto(priv) if priv != "S" else []),
                        test_data.add_testcase(f"{priv}_STI_sstc_stce_{stce}_sie_{enable}", coverpoint, covergroup),
                        *trigger_and_record(
                            test_data, sti, priv, r_val, r_mask, set_stimecmp_zero(priv, priv == "S" and stce == 1)
                        ),
                        *(goto("S") if priv != "S" else []),
                        *_cleanup_s(priv, r_temp),
                        *set_stce("S", r_temp, 0),
                        *preprocessor_endif(conditions),
                        "",
                    ]
                )
                test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _generate_enable_tests(test_data: TestData) -> list[str]:
    """Walk a single 1 through sie and raise every supervisor-level interrupt against it, from S and U mode.

    sstatus.SIE = 1, stvec direct.
    Expectation: the interrupt is taken only when its sie bit is the one that is set.
    """
    coverpoint = "cp_enable"
    lines = [comment_banner(coverpoint, _generate_enable_tests.__doc__)]
    for priv in PRIV_MODES:
        for enabled in S_INTERRUPTS:
            for intr in S_INTERRUPTS:
                r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
                conditions = [
                    supported_condition(enabled),
                    supported_condition(intr) if intr is not enabled else None,
                    MODE_CONDITION[priv],
                    tvec_condition(priv, 0),
                ]
                lines.extend(
                    [
                        *preprocessor_if(conditions),
                        *_setup_s(r_temp, priv, 1, 0, sie_value=1 << enabled.cause),
                        *(goto(priv) if priv != "S" else []),
                        test_data.add_testcase(f"{priv}_en_{enabled.name}_pend_{intr.name}", coverpoint, covergroup),
                        *trigger_and_record(test_data, intr, priv, r_val, r_mask),
                        *(goto("S") if priv != "S" else []),
                        *_cleanup_s(priv, r_temp),
                        *preprocessor_endif(conditions),
                        "",
                    ]
                )
                test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _priority_case(
    test_data: TestData,
    coverpoint: str,
    bin_name: str,
    priv: str,
    pending: list[Interrupt],
    enable: int,
    conditions: list[str | None],
) -> list[str]:
    """Raise every interrupt in pending with sie = 0, then write sie = enable and wait for the traps."""
    r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
    lines = [
        *preprocessor_if(conditions),
        *_setup_s(r_temp, priv, 1, 0, sie_value=0),
        *(goto(priv) if priv != "S" else []),
        test_data.add_testcase(bin_name, coverpoint, covergroup),
    ]
    lines.extend(raise_all(priv, pending))
    lines.extend(
        [
            *wait_pending(priv, pending, r_val, r_mask),
            "# Enable: the pending interrupts are now taken in priority order",
            *write_xie(priv, "sie", r_temp, enable),
            f"RVTEST_IDLE_FOR_INTERRUPT(x{r_val})",
            *COVERAGE_MARK,
            *read_pending_mask(priv, r_val, r_mask, pending),
            write_sigupd(r_val, test_data),
            *(goto("S") if priv != "S" else []),
            *_cleanup_s(priv, r_temp),
            *preprocessor_endif(conditions),
            "",
        ]
    )
    test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _generate_priority_sip_tests(test_data: TestData) -> list[str]:
    """Priority of pending interrupts: raise each pair with sie = 0s, then write sie = 1s.

    Expectation: both interrupts are taken, higher priority first.
    """
    coverpoint = "cp_priority_sip"
    lines = [comment_banner(coverpoint, _generate_priority_sip_tests.__doc__)]
    for priv in PRIV_MODES:
        for a, b in interrupt_pairs(S_INTERRUPTS):
            conditions = [supported_condition(a), supported_condition(b), MODE_CONDITION[priv], tvec_condition(priv, 0)]
            lines.extend(
                _priority_case(test_data, coverpoint, f"{priv}_{a.name}_{b.name}", priv, [a, b], -1, conditions)
            )
    return lines


def _generate_priority_sie_tests(test_data: TestData) -> list[str]:
    """Priority of enabled interrupts: raise every supervisor interrupt with sie = 0s, then enable each pair in sie.

    Expectation: the two enabled interrupts are taken, higher priority first; the rest stay pending.
    """
    coverpoint = "cp_priority_sie"
    lines = [comment_banner(coverpoint, _generate_priority_sie_tests.__doc__)]
    for priv in PRIV_MODES:
        for a, b in interrupt_pairs(S_INTERRUPTS):
            conditions = [supported_condition(a), supported_condition(b), MODE_CONDITION[priv], tvec_condition(priv, 0)]
            enable = (1 << a.cause) | (1 << b.cause)
            lines.extend(
                _priority_case(
                    test_data,
                    coverpoint,
                    f"{priv}_{a.name}_{b.name}",
                    priv,
                    raise_order(S_INTERRUPTS),
                    enable,
                    conditions,
                )
            )
    return lines


def _generate_wfi_tests(test_data: TestData) -> list[str]:
    """WFI waits for the supervisor timer interrupt (Sstc) in S-mode.

    menvcfg.STCE = 1 (through T-SBI), sstatus.SIE = {0/1}, mstatus.TW = 0, sie.STIE = 1;
    stimecmp = mtime + 16 * RVMODEL_TIMER_INT_SOON_DELAY written from S-mode, then WFI until the timer
    has fired. U-mode is not covered: WFI in U-mode may legally raise an illegal-instruction exception.
    Expectation: STI is taken unless SIE = 0, where it is left pending.
    """
    coverpoint = "cp_wfi"
    sti = INTERRUPT_BY_NAME["STI"]
    lines = [comment_banner(coverpoint, _generate_wfi_tests.__doc__)]
    for enable in (0, 1):
        r_temp, r_before, r_val = test_data.int_regs.get_registers(3)
        conditions = ["defined(SSTC_SUPPORTED)", supported_condition(sti), tvec_condition("S", 0)]
        lines.extend(
            [
                *preprocessor_if(conditions),
                *_setup_s(r_temp, "S", enable, 0, sie_value=1 << sti.cause),
                *set_stce("S", r_temp, 1),
                *set_tw("S", r_temp, 0),
                *arm_stimecmp_soon_s(r_val, r_temp, r_before, 16),
                *read_trap_count(r_before),
                test_data.add_testcase(f"S_sie_{enable}_tw_0", coverpoint, covergroup),
                *wfi_until_timer(r_before, r_val, None if enable else sti.cause, "sip"),
                *COVERAGE_MARK,
                *read_pending(sti, "S", r_val, r_temp),
                write_sigupd(r_val, test_data),
                *_cleanup_s("S", r_temp),
                *set_stce("S", r_temp, 0),
                *preprocessor_endif(conditions),
                "",
            ]
        )
        test_data.int_regs.return_registers([r_temp, r_before, r_val])
    return lines


def _generate_wfi_timeout_tests(test_data: TestData) -> list[str]:
    """WFI with mstatus.TW = 1 and no interrupt coming raises an illegal-instruction exception, from S and U mode.

    mstatus.TW = 1 and mie.MTIE = {0/1} are written through T-SBI; sstatus.SIE = {0/1}.
    Expectation: the exception is recorded; the number of traps taken across the WFI is 1.
    """
    coverpoint = "cp_wfi_timeout"
    lines = [comment_banner(coverpoint, _generate_wfi_timeout_tests.__doc__)]
    for priv in PRIV_MODES:
        for mtie in (0, 1):
            for sie in (0, 1):
                r_temp, r_before, r_val = test_data.int_regs.get_registers(3)
                conditions = [MODE_CONDITION[priv], tvec_condition(priv, 0)]
                lines.extend(
                    [
                        *preprocessor_if(conditions),
                        *_setup_s(r_temp, priv, sie, 0, sie_value=0),
                        f"LI(x{r_temp}, {mtie << 7:#x})",
                        tsbi_call(f"csrw mie, x{r_temp}"),
                        *set_tw("S", r_temp, 1),
                        *(goto(priv) if priv != "S" else []),
                        test_data.add_testcase(f"{priv}_mtie_{mtie}_sie_{sie}", coverpoint, covergroup),
                        *read_trap_count(r_before),
                        "wfi",
                        *COVERAGE_MARK,
                        *read_trap_count(r_val),
                        f"sub x{r_val}, x{r_val}, x{r_before}  # traps taken by WFI",
                        write_sigupd(r_val, test_data),
                        *(goto("S") if priv != "S" else []),
                        *_cleanup_s(priv, r_temp),
                        *set_tw("S", r_temp, 0),
                        *preprocessor_endif(conditions),
                        "",
                    ]
                )
                test_data.int_regs.return_registers([r_temp, r_before, r_val])
    return lines


@add_priv_test_generator("InterruptsS", required_extensions=["S"], extra_defines=["#define BOOT_TO_SMODE"])
def make_interruptss(test_data: TestData) -> list[TestChunk]:
    test_chunks: list[TestChunk] = []
    tc = test_data.begin_test_chunk()
    tc.code.extend(_generate_trigger_tests(test_data))
    tc.code.extend(_generate_trigger_reg_tests(test_data))
    tc.code.extend(_generate_trigger_sti_sstc_tests(test_data))
    tc.code.extend(_generate_enable_tests(test_data))
    tc.code.extend(_generate_priority_sip_tests(test_data))
    tc.code.extend(_generate_priority_sie_tests(test_data))
    tc.code.extend(_generate_wfi_tests(test_data))
    tc.code.extend(_generate_wfi_timeout_tests(test_data))
    test_chunks.append(test_data.end_test_chunk())
    return test_chunks
