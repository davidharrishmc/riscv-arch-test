##################################
# priv/extensions/InterruptsSm.py
#
# InterruptsSm privileged extension test generator.
# David_Harris@hmc.edu 29 August 2026
# SPDX-License-Identifier: Apache-2.0
##################################

"""Machine-level interrupt tests. Boots to M-mode and runs testcases in each of M, S and U mode."""

from testgen.asm.helpers import comment_banner, write_sigupd
from testgen.data.state import TestData
from testgen.data.test_chunk import TestChunk
from testgen.priv.extensions.InterruptsCommon import (
    COVERAGE_MARK,
    INTERRUPT_BY_NAME,
    INTERRUPTS,
    MODE_CONDITION,
    Interrupt,
    arm_mtimer_soon_m,
    clear_all,
    delegation_condition,
    goto,
    interrupt_pairs,
    pair_condition,
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

covergroup = "InterruptsSm_cg"
PRIV_MODES = ("M", "S", "U")


def _setup_m(r_temp: int, priv: str, enable: int, deleg: int, tvec: int, mie_value: int | None = None) -> list[str]:
    """M-mode configuration before a testcase that runs in mode priv.

    enable is mstatus.MIE for M-mode testcases and sstatus.SIE otherwise; mstatus.MIE is 1
    below M-mode so that nothing is masked on the way back to M-mode. mie is all ones unless
    mie_value is given.
    """
    lines = [
        "# Setup (M-mode): disable and clear everything before configuring",
        "csrw mie, zero",
        "csrci mstatus, 8  # mstatus.MIE = 0",
        "#ifdef S_SUPPORTED",
        "csrci mstatus, 2  # sstatus.SIE = 0",
        "csrw mideleg, zero",
        "#endif",
        *clear_all("M", r_temp),
        *set_tvec_mode(priv, tvec),
    ]
    if deleg:
        lines.extend(["# Delegate every supervisor-level interrupt", f"LI(x{r_temp}, -1)", f"csrw mideleg, x{r_temp}"])
    if mie_value is None:
        lines.extend(["# Enable every interrupt source", f"LI(x{r_temp}, -1)", f"csrw mie, x{r_temp}"])
    else:
        lines.extend([f"# mie = {mie_value:#x}", f"LI(x{r_temp}, {mie_value:#x})", f"csrw mie, x{r_temp}"])
    if priv == "M":
        lines.extend(["#ifdef S_SUPPORTED", "csrsi sstatus, 2  # sstatus.SIE = 1", "#endif"])
        lines.append(f"{'csrsi' if enable else 'csrci'} mstatus, 8  # mstatus.MIE = {enable}")
    else:
        lines.extend(
            [
                f"{'csrsi' if enable else 'csrci'} sstatus, 2  # sstatus.SIE = {enable}",
                "csrsi mstatus, 8  # mstatus.MIE = 1",
            ]
        )
    return lines


def _cleanup_m(priv: str, r_temp: int) -> list[str]:
    return [
        "# Cleanup (M-mode)",
        "csrw mie, zero",
        "csrci mstatus, 8",
        *clear_all("M", r_temp),
        "#ifdef S_SUPPORTED",
        "csrci mstatus, 2",
        "csrw mideleg, zero",
        "#endif",
        *restore_tvec_mode(priv),
    ]


def _trigger_case(
    test_data: TestData,
    coverpoint: str,
    intr: Interrupt,
    priv: str,
    enable: int,
    deleg: int,
    tvec: int,
    csr: str | None = None,
) -> list[str]:
    """One testcase: configure in M-mode, hop to priv, raise intr (by macro, or by a csr write), wait, clean up."""
    r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
    conditions = [
        supported_condition(intr),
        MODE_CONDITION[priv],
        delegation_condition(intr) if deleg else None,
        tvec_condition(priv, tvec),
    ]
    enable_name = "mie" if priv == "M" else "sie"
    via = f"_{csr}" if csr else ""
    lines = [
        *preprocessor_if(conditions),
        *_setup_m(r_temp, priv, enable, deleg, tvec),
        *(goto(priv) if priv != "M" else []),
        test_data.add_testcase(
            f"{priv}_{intr.name}{via}_{enable_name}_{enable}_deleg_{deleg}_tvec_{tvec}", coverpoint, covergroup
        ),
        *trigger_and_record(
            test_data, intr, priv, r_val, r_mask, set_pending_csr(intr, priv, csr, r_mask) if csr else None
        ),
        *(goto("M") if priv != "M" else []),
        *_cleanup_m(priv, r_temp),
        *preprocessor_endif(conditions),
        "",
    ]
    test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _generate_trigger_tests(test_data: TestData) -> list[str]:
    """Raise each supported interrupt from M, S and U mode.

    M-mode: mstatus.MIE = {0/1}, mideleg = {0s/1s}, mie = 1s, mtvec.MODE = {direct, vectored}
    S/U-mode: sstatus.SIE = {0/1}, mideleg = {0s/1s}, mie = 1s, stvec.MODE = {direct, vectored}
    Expectation: pending if supported and not delegated away from the current mode; trap if enabled.
    """
    coverpoint = "cp_trigger"
    lines = [comment_banner(coverpoint, _generate_trigger_tests.__doc__)]
    for priv in PRIV_MODES:
        for intr in INTERRUPTS:
            for deleg in (0, 1) if intr.level == "S" else (0,):
                for enable in (0, 1):
                    for tvec in (0, 1):
                        lines.extend(_trigger_case(test_data, coverpoint, intr, priv, enable, deleg, tvec))
    return lines


def _generate_trigger_reg_tests(test_data: TestData) -> list[str]:
    """Like cp_trigger, but raise SSI and SEI by writing the pending register instead of the platform macro.

    M-mode writes mip.SSIP and mip.SEIP; S-mode writes sip.SSIP directly and mip.SSIP/mip.SEIP through
    T-SBI; U-mode writes all three through T-SBI.
    """
    coverpoint = "cp_trigger_reg"
    lines = [comment_banner(coverpoint, _generate_trigger_reg_tests.__doc__)]
    ssi, sei = INTERRUPT_BY_NAME["SSI"], INTERRUPT_BY_NAME["SEI"]
    cases = {"M": [(ssi, "mip"), (sei, "mip")], "S": [(ssi, "sip"), (ssi, "mip"), (sei, "mip")]}
    cases["U"] = cases["S"]
    for priv in PRIV_MODES:
        for intr, csr in cases[priv]:
            for deleg in (0, 1):
                if csr == "sip" and not deleg:
                    continue  # sip.SSIP is only writable when SSI is delegated
                for enable in (0, 1):
                    for tvec in (0, 1):
                        lines.extend(_trigger_case(test_data, coverpoint, intr, priv, enable, deleg, tvec, csr))
    return lines


def _generate_trigger_sti_sstc_tests(test_data: TestData) -> list[str]:
    """Raise STI through Sstc (stimecmp = 0) from M, S and U mode with menvcfg.STCE = {0/1}.

    M-mode: mstatus.MIE = {0/1}; S/U-mode: sstatus.SIE = {0/1}; mideleg = {0s/1s}; mie = 1s.
    stimecmp is written directly where the mode may access it (M-mode, S-mode with STCE = 1) and
    through T-SBI otherwise.
    Expectation: STI only when STCE = 1, then as for cp_trigger.
    """
    coverpoint = "cp_trigger_sti_sstc"
    sti = INTERRUPT_BY_NAME["STI"]
    lines = [comment_banner(coverpoint, _generate_trigger_sti_sstc_tests.__doc__)]
    for priv in PRIV_MODES:
        for stce in (0, 1):
            for deleg in (0, 1):
                for enable in (0, 1):
                    r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
                    conditions = [
                        "defined(SSTC_SUPPORTED)",
                        supported_condition(sti),
                        MODE_CONDITION[priv],
                        delegation_condition(sti) if deleg else None,
                    ]
                    enable_name = "mie" if priv == "M" else "sie"
                    lines.extend(
                        [
                            *preprocessor_if(conditions),
                            *_setup_m(r_temp, priv, enable, deleg, 0),
                            *set_stce("M", r_temp, stce),
                            *(goto(priv) if priv != "M" else []),
                            test_data.add_testcase(
                                f"{priv}_STI_sstc_stce_{stce}_{enable_name}_{enable}_deleg_{deleg}",
                                coverpoint,
                                covergroup,
                            ),
                            *trigger_and_record(
                                test_data,
                                sti,
                                priv,
                                r_val,
                                r_mask,
                                set_stimecmp_zero(priv, priv == "M" or (priv == "S" and stce == 1)),
                            ),
                            *(goto("M") if priv != "M" else []),
                            *_cleanup_m(priv, r_temp),
                            *set_stce("M", r_temp, 0),
                            *preprocessor_endif(conditions),
                            "",
                        ]
                    )
                    test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _generate_enable_tests(test_data: TestData) -> list[str]:
    """Walk a single 1 through mie and raise every interrupt against it, from M, S and U mode.

    mstatus.MIE = 1 (sstatus.SIE = 1 below M-mode); mideleg = 0s in M-mode and 1s below it so that
    the walking bit also acts as sie; mtvec/stvec direct.
    Expectation: the interrupt is taken only when its mie bit is the one that is set.
    """
    coverpoint = "cp_enable"
    lines = [comment_banner(coverpoint, _generate_enable_tests.__doc__)]
    for priv in PRIV_MODES:
        deleg = 0 if priv == "M" else 1
        for enabled in INTERRUPTS:
            for intr in INTERRUPTS:
                r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
                conditions = [
                    supported_condition(enabled),
                    supported_condition(intr) if intr is not enabled else None,
                    MODE_CONDITION[priv],
                    delegation_condition(intr) if deleg and intr.level == "S" else None,
                    tvec_condition(priv, 0),
                ]
                lines.extend(
                    [
                        *preprocessor_if(conditions),
                        *_setup_m(r_temp, priv, 1, deleg, 0, mie_value=1 << enabled.cause),
                        *(goto(priv) if priv != "M" else []),
                        test_data.add_testcase(f"{priv}_en_{enabled.name}_pend_{intr.name}", coverpoint, covergroup),
                        *trigger_and_record(test_data, intr, priv, r_val, r_mask),
                        *(goto("M") if priv != "M" else []),
                        *_cleanup_m(priv, r_temp),
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
    deleg: int | str,
    pending: list[Interrupt],
    enable: int | str,
    conditions: list[str | None],
    raise_extra: dict[str, str] | None = None,
) -> list[str]:
    """Raise every interrupt in pending with mie = 0, then write mie = enable and wait for the traps.

    deleg is 0/1 (all supervisor interrupts) or a mideleg value; enable is a mie value.
    """
    r_temp, r_val, r_mask = test_data.int_regs.get_registers(3)
    mideleg_lines = [] if isinstance(deleg, int) else [f"LI(x{r_temp}, {deleg})", f"csrw mideleg, x{r_temp}"]
    lines = [
        *preprocessor_if(conditions),
        *_setup_m(r_temp, priv, 1, 0 if isinstance(deleg, str) else deleg, 0, mie_value=0),
        *mideleg_lines,
        *(goto(priv) if priv != "M" else []),
        test_data.add_testcase(bin_name, coverpoint, covergroup),
    ]
    lines.extend(raise_all(priv, pending, raise_extra))
    lines.extend(
        [
            *wait_pending(priv, pending, r_val, r_mask, raise_extra),
            "# Enable: the pending interrupts are now taken in priority order",
            *write_xie(priv, "mie", r_temp, enable),
            f"RVTEST_IDLE_FOR_INTERRUPT(x{r_val})",
            *COVERAGE_MARK,
            *read_pending_mask(priv, r_val, r_mask, pending),
            write_sigupd(r_val, test_data),
            *(goto("M") if priv != "M" else []),
            *_cleanup_m(priv, r_temp),
            *preprocessor_endif(conditions),
            "",
        ]
    )
    test_data.int_regs.return_registers([r_temp, r_val, r_mask])
    return lines


def _generate_priority_mip_tests(test_data: TestData) -> list[str]:
    """Priority of pending interrupts: raise each pair with mie = 0s, then write mie = 1s.

    M-mode: mideleg = 0s; S/U-mode: mideleg = 1s.
    Expectation: both interrupts are taken, higher priority first (machine-level before delegated).
    """
    coverpoint = "cp_priority_mip"
    lines = [comment_banner(coverpoint, _generate_priority_mip_tests.__doc__)]
    for priv in PRIV_MODES:
        deleg = 0 if priv == "M" else 1
        for a, b in interrupt_pairs():
            conditions = [
                supported_condition(a),
                supported_condition(b),
                pair_condition(a, b),
                MODE_CONDITION[priv],
                tvec_condition(priv, 0),
            ]
            lines.extend(
                _priority_case(test_data, coverpoint, f"{priv}_{a.name}_{b.name}", priv, deleg, [a, b], -1, conditions)
            )
    return lines


def _generate_priority_mie_tests(test_data: TestData) -> list[str]:
    """Priority of enabled interrupts: raise every interrupt with mie = 0s, then enable each pair in mie.

    M-mode: mideleg = 0s; S/U-mode: mideleg = 1s.
    Expectation: the two enabled interrupts are taken, higher priority first; the rest stay pending.
    """
    coverpoint = "cp_priority_mie"
    lines = [comment_banner(coverpoint, _generate_priority_mie_tests.__doc__)]
    for priv in PRIV_MODES:
        deleg = 0 if priv == "M" else 1
        for a, b in interrupt_pairs():
            conditions = [
                supported_condition(a),
                supported_condition(b),
                pair_condition(a, b),
                MODE_CONDITION[priv],
                tvec_condition(priv, 0),
            ]
            enable = (1 << a.cause) | (1 << b.cause)
            # clearing an enabled MEI drops a pending SEI when one PLIC source feeds both contexts
            extra = {"SEI": "!defined(RVMODEL_SEXT_MEXT_SHARED_SOURCE)"} if "MEI" in (a.name, b.name) else None
            lines.extend(
                _priority_case(
                    test_data,
                    coverpoint,
                    f"{priv}_{a.name}_{b.name}",
                    priv,
                    deleg,
                    raise_order(INTERRUPTS),
                    enable,
                    conditions,
                    extra,
                )
            )
    return lines


def _generate_priority_mideleg_tests(test_data: TestData) -> list[str]:
    """Priority of delegated interrupts: raise each pair with mie = 0s and exactly one of the pair delegated, then mie = 1s.

    Expectation: in M-mode only the non-delegated interrupt is taken; below M-mode the machine-level or
    non-delegated interrupt is taken into M-mode first, then the delegated one into S-mode.
    """
    coverpoint = "cp_priority_mideleg"
    lines = [comment_banner(coverpoint, _generate_priority_mideleg_tests.__doc__)]
    for priv in PRIV_MODES:
        for a, b in interrupt_pairs():
            for d in (a, b):
                if d.level != "S":
                    continue
                conditions = [
                    supported_condition(a),
                    supported_condition(b),
                    pair_condition(a, b),
                    delegation_condition(d),
                    MODE_CONDITION[priv],
                    tvec_condition(priv, 0),
                ]
                lines.extend(
                    _priority_case(
                        test_data,
                        coverpoint,
                        f"{priv}_{a.name}_{b.name}_deleg_{d.name}",
                        priv,
                        f"{1 << d.cause:#x}",
                        [a, b],
                        -1,
                        conditions,
                    )
                )
    return lines


def _generate_wfi_tests(test_data: TestData) -> list[str]:
    """WFI waits for the machine timer interrupt, from M and S mode.

    M-mode: mstatus.MIE = {0/1}, mstatus.TW = {0/1}; S-mode: sstatus.SIE = {0/1}, TW = 0; mie.MTIE = 1.
    mtimecmp = mtime + RVMODEL_TIMER_INT_SOON_DELAY (times 8 when armed before hopping to S-mode),
    then WFI until the timer has fired. U-mode is not covered: WFI in U-mode may legally raise an
    illegal-instruction exception instead of waiting.
    Expectation: MTI is taken (into M-mode) unless MIE = 0 in M-mode, where it is left pending; MIE,
    SIE and TW do not otherwise affect the result.
    """
    coverpoint = "cp_wfi"
    mti = INTERRUPT_BY_NAME["MTI"]
    lines = [comment_banner(coverpoint, _generate_wfi_tests.__doc__)]
    for priv in ("M", "S"):
        for tw in (0, 1) if priv == "M" else (0,):
            for enable in (0, 1):
                regs = test_data.int_regs.get_registers(6)
                r_temp, r_before, r_val = regs[:3]
                conditions = [supported_condition(mti), MODE_CONDITION[priv], tvec_condition(priv, 0)]
                enable_name = "mie" if priv == "M" else "sie"
                lines.extend(
                    [
                        *preprocessor_if(conditions),
                        *_setup_m(r_temp, priv, enable, 0, 0, mie_value=1 << mti.cause),
                        *set_tw("M", r_temp, tw),
                        *arm_mtimer_soon_m(regs, 1 if priv == "M" else 8),
                        *(goto(priv) if priv != "M" else []),
                        *read_trap_count(r_before),
                        test_data.add_testcase(f"{priv}_{enable_name}_{enable}_tw_{tw}", coverpoint, covergroup),
                        *wfi_until_timer(r_before, r_val, mti.cause if priv == "M" and enable == 0 else None),
                        *COVERAGE_MARK,
                        *read_pending(mti, priv, r_val, r_temp),
                        write_sigupd(r_val, test_data),
                        *(goto("M") if priv != "M" else []),
                        *_cleanup_m(priv, r_temp),
                        *set_tw("M", r_temp, 0),
                        *preprocessor_endif(conditions),
                        "",
                    ]
                )
                test_data.int_regs.return_registers(regs)
    return lines


def _generate_wfi_timeout_tests(test_data: TestData) -> list[str]:
    """WFI below M-mode with mstatus.TW = 1 and no interrupt coming raises an illegal-instruction exception.

    mstatus.MIE = {0/1}, mie.MTIE = {0/1}, sstatus.SIE = 1, timers disarmed.
    Expectation: the exception is recorded; the number of traps taken across the WFI is 1.
    """
    coverpoint = "cp_wfi_timeout"
    lines = [comment_banner(coverpoint, _generate_wfi_timeout_tests.__doc__)]
    for priv in ("S", "U"):
        for mie in (0, 1):
            for mtie in (0, 1):
                r_temp, r_before, r_val = test_data.int_regs.get_registers(3)
                conditions = [MODE_CONDITION[priv], tvec_condition(priv, 0)]
                lines.extend(
                    [
                        *preprocessor_if(conditions),
                        *_setup_m(r_temp, priv, 1, 0, 0, mie_value=mtie << 7),
                        f"{'csrsi' if mie else 'csrci'} mstatus, 8  # mstatus.MIE = {mie}",
                        *set_tw("M", r_temp, 1),
                        *(goto(priv) if priv != "M" else []),
                        test_data.add_testcase(f"{priv}_mie_{mie}_mtie_{mtie}", coverpoint, covergroup),
                        *read_trap_count(r_before),
                        "wfi",
                        *COVERAGE_MARK,
                        *read_trap_count(r_val),
                        f"sub x{r_val}, x{r_val}, x{r_before}  # traps taken by WFI",
                        write_sigupd(r_val, test_data),
                        *(goto("M") if priv != "M" else []),
                        *_cleanup_m(priv, r_temp),
                        *set_tw("M", r_temp, 0),
                        *preprocessor_endif(conditions),
                        "",
                    ]
                )
                test_data.int_regs.return_registers([r_temp, r_before, r_val])
    return lines


@add_priv_test_generator("InterruptsSm", required_extensions=["Sm"], extra_defines=["#define BOOT_TO_MMODE"])
def make_interruptssm(test_data: TestData) -> list[TestChunk]:
    test_chunks: list[TestChunk] = []
    tc = test_data.begin_test_chunk()
    tc.code.extend(_generate_trigger_tests(test_data))
    tc.code.extend(_generate_trigger_reg_tests(test_data))
    tc.code.extend(_generate_trigger_sti_sstc_tests(test_data))
    tc.code.extend(_generate_enable_tests(test_data))
    tc.code.extend(_generate_priority_mip_tests(test_data))
    tc.code.extend(_generate_priority_mie_tests(test_data))
    tc.code.extend(_generate_priority_mideleg_tests(test_data))
    tc.code.extend(_generate_wfi_tests(test_data))
    tc.code.extend(_generate_wfi_timeout_tests(test_data))
    test_chunks.append(test_data.end_test_chunk())
    return test_chunks
