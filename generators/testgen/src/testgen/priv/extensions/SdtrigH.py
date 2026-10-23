##################################
# SdtrigH.py
#
# Sdtrig hypervisor test generator: triggers in VS-mode and VU-mode, hcontext, and the H-only textra selects.
# David_Harris@hmc.edu 19 October 2026
# SPDX-License-Identifier: Apache-2.0
##################################

"""SdtrigH test generator.

The suite boots to HS-mode and enters VS-mode and VU-mode from HS-mode, arming triggers through T-SBI as SdtrigS
and SdtrigU do.  While a guest runs, medeleg[3] = hedeleg[3] = 1, so its breakpoints are taken into VS-mode, and
vsstatus.SIE = 1: with that delegation the Sdtrig re-entrancy rule suppresses VS-mode triggers while vsstatus.SIE
is 0 (VU-mode triggers are never suppressed).  A breakpoint taken into VS-mode writes no GVA bit, which an
implementation may or may not set when an icount breakpoint writes zero to stval.  On a hart whose medeleg[3] is
read-only 0 the breakpoints are taken into M-mode instead.

Each case is gated on the DUT's Sdtrig parameters from riscv-unified-db: the trigger types each tselect supports,
the writable vs/vu bits, the itrigger and etrigger codes, the textra matches and their mhvalue/svalue lengths, and
which context CSRs exist.

itrigger and etrigger fire before the first instruction of the handler of the trap they match.  Their tests arm
the trigger in M-mode with medeleg[3] = 0 and take an SSI or a virtual-instruction exception from the guest into
HS-mode, so the breakpoint is taken into M-mode, where no re-entrancy option suppresses it.

The textra cases arm an icount trigger (count = 1) whose breakpoint is taken on a marker instruction, and run under
the translation that their select needs: hgatp = Sv39x4/Sv32x4 with a VMID for mhselect = 2/6, and
vsatp = Sv39/Sv32 with an ASID for sselect = 2.  satp, vsatp and hgatp never hold MODE = Bare with a nonzero
ASID or VMID, whose effect is UNSPECIFIED.
"""

from random import seed

from testgen.asm.helpers import comment_banner, reproducible_hash, write_sigupd
from testgen.data.random import random_int
from testgen.data.state import TestData
from testgen.data.test_chunk import TestChunk
from testgen.priv.extensions.HCommon import ATP_GATE
from testgen.priv.extensions.InterruptsCommon import guard_symbol
from testgen.priv.extensions.SdtrigCommon import (
    _ASID_X,
    _MCONTEXT_MATCH_GATE,
    _TEXTRA_ASID_CASES,
    MODE_PRIVBIT,
    SDTRIG_DEFINES,
    TRIGGERS,
    _add_tc,
    _cause_interrupt,
    _clear_interrupt,
    _close_gates,
    _config_etrigger,
    _config_icount,
    _config_itrigger,
    _config_mcontrol6,
    _csr_access,
    _disable_trigger,
    _icount_gates,
    _mcontrol6_gates,
    _mode_writable,
    _set_medeleg,
    _sign_trap_count,
    _svalue,
    _textra_expr,
    _xlen_li_expr,
    _xsl_ifdefs,
)
from testgen.priv.extensions.StateenHCommon import hstateen0_bit, mstateen0_bit, read_in_mode
from testgen.priv.extensions.sv.generate import guest_translation_setup, guest_translation_teardown, per_xlen
from testgen.priv.registry import add_priv_test_generator

GUESTS = ("Vs", "Vu")
_GOTO = {"Vs": "RVTEST_TSBI_GOTO_VSMODE", "Vu": "RVTEST_TSBI_GOTO_VUMODE"}
_ALL_PRIV = 0b11111
# An icount trigger armed with count = 1 counts the instruction after the T-SBI call and is taken before the marker.
# Coverage samples the marker by its encoding when the trigger does not fire.  norvc keeps it a 32-bit instruction.
_MARKER = [
    ".option push",
    ".option norvc",
    "addi x0, x0, 0x5a # marker: an icount breakpoint is taken here",
    ".option pop",
]
_SSI_CODE = 1
_VIRTUAL_INSTRUCTION = 22

MSTATEEN0_CONTEXT = ("MSTATEEN0_HCONTEXT", "MSTATEEN0H_HCONTEXT")
HSTATEEN0_CONTEXT = ("HSTATEEN0_SCONTEXT", "HSTATEEN0H_SCONTEXT")

# mhselect = 1/5 (2/6) compares {mhvalue, mhselect[2]} with mcontext (hgatp.VMID).  The contexts and VMIDs are
# limited to the implemented {mhvalue, mhselect[2]} bits, so a case expected to match still matches.
_MHVALUE_SEL_MASK = "((1 << (UDB_SDTRIG_TEXTRA_MHVALUE_LEN + 1)) - 1)"
# (case, mcontext on RV32, mcontext on RV64): one context of each parity matches only one of the two encodings
_MCTX_CONTEXTS = (("even", 0x54, 0x2AAA), ("odd", 0x55, 0x2AAB))
# VMIDs for mhselect = 2/6, an even and an odd value that fit in hgatp.VMID
_VMIDS = (
    ("even", f"(((1 << UDB_VMID_WIDTH) - 2) & {_MHVALUE_SEL_MASK})"),
    ("odd", f"(((1 << UDB_VMID_WIDTH) - 1) & {_MHVALUE_SEL_MASK})"),
)


def _mhselect_cases(odd: bool) -> list[tuple[str, int, int]]:
    """(case, mhselect, mhvalue xor) for a context whose bit 0 is odd: the matching select, the other select, and
    the matching select with mhvalue bit 0 flipped."""
    own, other = (5, 1) if odd else (1, 5)
    return [(f"sel{own}_match", own, 0), (f"sel{other}_bit0", other, 0), (f"sel{own}_mhvalue", own, 1)]


def _enter_guest(mode: str, reg: int) -> list[str]:
    """From HS-mode, delegate breakpoints to VS-mode, set vsstatus.SIE and enter mode."""
    return [
        f"LI(x{reg}, 0x{1 << 3:x})",
        f"csrs hedeleg, x{reg} # hedeleg[3]=1: guest breakpoints are taken into VS-mode",
        "csrsi vsstatus, 0x2 # vsstatus.SIE=1 so VS-mode triggers are not suppressed",
        _GOTO[mode],
    ]


def _leave_guest(reg: int) -> list[str]:
    """Return to HS-mode and undo _enter_guest."""
    return [
        "RVTEST_TSBI_GOTO_SMODE",
        "csrci vsstatus, 0x2",
        f"LI(x{reg}, 0x{1 << 3:x})",
        f"csrc hedeleg, x{reg}",
    ]


def _mode_bit_tests(test_data: TestData, mode: str) -> list[str]:
    """mcontrol6 and icount triggers in mode with only mode's vs/vu bit set, then with every other mode bit set."""
    cfg_reg, addr_reg, data_reg, temp_reg = test_data.int_regs.get_registers(4)
    own = MODE_PRIVBIT[mode]
    cases = (("own", own), ("others", _ALL_PRIV ^ own))
    m = mode.lower()
    lines = [
        comment_banner(
            f"cp_mcontrol6_{m}, cp_icount_{m}",
            f"mcontrol6 (store address) and icount (count = 1) triggers in {mode.upper()}-mode with tdata1.{m} = 1\n"
            f"and the other mode bits 0, then with tdata1.{m} = 0 and the other mode bits 1.\n"
            "The breakpoint is taken into VS-mode only in the first case",
        ),
        *_enter_guest(mode, temp_reg),
    ]
    for trig_num in TRIGGERS:
        gates = [*_mcontrol6_gates(trig_num, mode), *_xsl_ifdefs(0b010)]
        lines.extend(gates)
        for name, priv in cases:
            lines.extend(
                [
                    _add_tc(test_data, f"trig_num_{trig_num}_{name}", f"cp_mcontrol6_{m}", "SdtrigH_mcontrol6_cg"),
                    *_config_mcontrol6(cfg_reg, trig_num, "scratch", mode, privbits=priv, xsl=0b010, select=0),
                    f"LA(x{addr_reg}, scratch)",
                    f"LI(x{data_reg}, {random_int(32, signed=False)})",
                    f"sw x{data_reg}, 0(x{addr_reg}) # breakpoint iff tdata1.{m} = 1",
                    "nop # spacer",
                    *_disable_trigger(cfg_reg, trig_num, mode),
                    *_sign_trap_count(temp_reg, test_data),
                ]
            )
        lines.extend(_close_gates(gates))
    for trig_num in TRIGGERS:
        gates = _icount_gates(trig_num, mode)
        lines.extend(["", *gates])
        for name, priv in cases:
            lines.extend(
                [
                    _add_tc(test_data, f"trig_num_{trig_num}_{name}", f"cp_icount_{m}", "SdtrigH_icount_cg"),
                    *_config_icount(cfg_reg, trig_num, 1, mode, privbits=priv),
                    f"nop # counted when tdata1.{m} = 1",
                    *_MARKER,
                    *_disable_trigger(cfg_reg, trig_num, mode),
                    *_sign_trap_count(temp_reg, test_data),
                ]
            )
        lines.extend(_close_gates(gates))
    lines.extend(_leave_guest(temp_reg))
    test_data.int_regs.return_registers([cfg_reg, addr_reg, data_reg, temp_reg])
    return lines


def _trap_trigger_tests(test_data: TestData) -> list[str]:
    """itrigger on SSI and etrigger on virtual instruction, armed in M-mode, with the trap taken from VS or VU."""
    cfg_reg, data_reg, temp_reg = test_data.int_regs.get_registers(3)
    ssi_guard = guard_symbol("SSI")
    lines = [
        comment_banner(
            "cp_itrigger_vs, cp_itrigger_vu, cp_etrigger_vs, cp_etrigger_vu",
            "itrigger selecting SSI and etrigger selecting virtual instruction, armed in M-mode with medeleg[3] = 0,\n"
            "with only the guest mode's vs/vu bit set and then with every other mode bit set.  The SSI is taken\n"
            "from the guest into HS-mode as the T-SBI call enters it, and the virtual instruction is a read of\n"
            "hstatus in the guest.  The trigger fires into M-mode before the first HS handler instruction only\n"
            "in the first case",
        ),
        "RVTEST_TSBI_GOTO_MMODE",
        *_set_medeleg(temp_reg, 3, False),
    ]
    for mode in GUESTS:
        m = mode.lower()
        own = MODE_PRIVBIT[mode]
        cases = (("own", own), ("others", _ALL_PRIV ^ own))
        itrigger_gates = [
            f"\n#ifdef {_mode_writable(mode)}",
            f"#ifdef {ssi_guard}",
            f"#ifdef UDB_SDTRIG_ITRIGGER_SUPPORTED_INTERRUPTS_{_SSI_CODE}",
        ]
        lines.extend(itrigger_gates)
        for trig_num in TRIGGERS:
            lines.append(f"#ifdef UDB_SDTRIG_ITRIGGER_SUPPORTED_TRIGGERS_{trig_num}")
            for name, priv in cases:
                lines.extend(
                    [
                        _add_tc(test_data, f"trig_num_{trig_num}_{name}", f"cp_itrigger_{m}", "SdtrigH_itrigger_cg"),
                        *_config_itrigger(cfg_reg, trig_num, 1 << _SSI_CODE, "Sm", privbits=priv),
                        *_cause_interrupt(_SSI_CODE, "Sm", temp_reg),
                        f"{_GOTO[mode]} # the SSI is taken from {mode.upper()}-mode into HS-mode",
                        "nop # spacer",
                        "RVTEST_TSBI_GOTO_MMODE",
                        *_clear_interrupt(_SSI_CODE, "Sm"),
                        f"LI(x{temp_reg}, 0x{1 << _SSI_CODE:x})",
                        f"csrc mie, x{temp_reg} # SSIE=0",
                        *_disable_trigger(cfg_reg, trig_num, "Sm"),
                        *_sign_trap_count(temp_reg, test_data),
                    ]
                )
            lines.append(f"#endif // UDB_SDTRIG_ITRIGGER_SUPPORTED_TRIGGERS_{trig_num}")
        lines.extend(_close_gates(itrigger_gates))
        etrigger_gates = [
            f"\n#ifdef {_mode_writable(mode)}",
            f"#ifdef UDB_SDTRIG_ETRIGGER_SUPPORTED_EXCEPTIONS_{_VIRTUAL_INSTRUCTION}",
        ]
        lines.extend(etrigger_gates)
        for trig_num in TRIGGERS:
            lines.append(f"#ifdef UDB_SDTRIG_ETRIGGER_SUPPORTED_TRIGGERS_{trig_num}")
            for name, priv in cases:
                lines.extend(
                    [
                        _add_tc(test_data, f"trig_num_{trig_num}_{name}", f"cp_etrigger_{m}", "SdtrigH_etrigger_cg"),
                        *_config_etrigger(cfg_reg, trig_num, 1 << _VIRTUAL_INSTRUCTION, "Sm", privbits=priv),
                        _GOTO[mode],
                        f"csrr x{data_reg}, hstatus # virtual instruction from {mode.upper()}-mode, taken into HS-mode",
                        "RVTEST_TSBI_GOTO_MMODE",
                        *_disable_trigger(cfg_reg, trig_num, "Sm"),
                        *_sign_trap_count(temp_reg, test_data),
                    ]
                )
            lines.append(f"#endif // UDB_SDTRIG_ETRIGGER_SUPPORTED_TRIGGERS_{trig_num}")
        lines.extend(_close_gates(etrigger_gates))
    lines.extend([*_set_medeleg(temp_reg, 3, True), "RVTEST_TSBI_GOTO_SMODE"])
    test_data.int_regs.return_registers([cfg_reg, data_reg, temp_reg])
    return lines


def _icount_textra_case(
    test_data: TestData,
    mode: str,
    binname: str,
    coverpoint: str,
    tdata3: list[str],
    regs: tuple[int, int],
    sign_in_hs: bool = False,
) -> list[str]:
    """Arm an icount trigger (count = 1) for mode with tdata3 on each trigger, run to the marker, disarm it, and sign
    the trap count, in HS-mode when sign_in_hs."""
    cfg_reg, temp_reg = regs
    lines: list[str] = []
    for trig_num in TRIGGERS:
        gates = _icount_gates(trig_num, mode)
        lines.extend(
            [
                *gates,
                _add_tc(test_data, f"trig_num_{trig_num}_{binname}", coverpoint, "SdtrigH_textra_cg"),
                *_config_icount(cfg_reg, trig_num, 1, mode, tdata3=tdata3),
                "nop # counted",
                *_MARKER,
                *_disable_trigger(cfg_reg, trig_num, mode),
                *(["RVTEST_TSBI_GOTO_SMODE"] if sign_in_hs else []),
                *_sign_trap_count(temp_reg, test_data),
                *([_GOTO[mode]] if sign_in_hs else []),
                *_close_gates(gates),
            ]
        )
    return lines


def _mhselect_tdata3(reg: int, mhselect: int, value32: str, value64: str, flip: int) -> list[str]:
    """tdata3 with mhselect and mhvalue = (value >> 1) ^ flip, for assembler expressions value32 and value64."""
    return _xlen_li_expr(
        reg,
        _textra_expr(32, mhselect=mhselect, mhvalue=f"(({value32}) >> 1) ^ {flip}"),
        _textra_expr(64, mhselect=mhselect, mhvalue=f"(({value64}) >> 1) ^ {flip}"),
    )


def _textra_mctx_tests(test_data: TestData) -> list[str]:
    """mhselect = 1/5 in VS-mode and VU-mode."""
    cfg_reg, temp_reg = test_data.int_regs.get_registers(2)
    coverpoint = "cp_textra_mctx_sel"
    lines = [
        comment_banner(
            coverpoint,
            "textra mhselect = 1 and 5: icount fires in VS-mode and VU-mode only when {mhvalue, mhselect[2]}\n"
            "equals the low bits of mcontext, for an even and an odd mcontext",
        ),
        _MCONTEXT_MATCH_GATE,
    ]
    for mode in GUESTS:
        lines.extend(_enter_guest(mode, temp_reg))
        for ctx_name, ctx32, ctx64 in _MCTX_CONTEXTS:
            ctx = (f"(0x{ctx32:x} & {_MHVALUE_SEL_MASK})", f"(0x{ctx64:x} & {_MHVALUE_SEL_MASK})")
            lines.extend(
                [
                    *_xlen_li_expr(temp_reg, *ctx),
                    _csr_access(f"csrw mcontext, x{temp_reg} # mcontext = {ctx_name} context", mode),
                ]
            )
            for case, mhselect, flip in _mhselect_cases(ctx_name == "odd"):
                lines.extend(
                    _icount_textra_case(
                        test_data,
                        mode,
                        f"{mode.lower()}_{ctx_name}_{case}",
                        coverpoint,
                        _mhselect_tdata3(cfg_reg, mhselect, *ctx, flip),
                        (cfg_reg, temp_reg),
                    )
                )
        lines.extend([_csr_access("csrw mcontext, x0 # clear the test context", mode), *_leave_guest(temp_reg)])
    lines.append("#endif // mcontext textra match")
    test_data.int_regs.return_registers([cfg_reg, temp_reg])
    return lines


def _textra_vmid_tests(test_data: TestData) -> list[str]:
    """mhselect = 2/6 in VS-mode and VU-mode with hgatp = Sv39x4/Sv32x4 identity mapping the test image."""
    cfg_reg, temp_reg, vmid_reg = test_data.int_regs.get_registers(3)
    coverpoint = "cp_textra_vmid_sel"
    lines = [
        comment_banner(
            coverpoint,
            "textra mhselect = 2 and 6: icount fires in VS-mode and VU-mode only when {mhvalue, mhselect[2]}\n"
            "equals hgatp.VMID, for an even and an odd VMID.  hgatp identity maps the test image",
        ),
        (
            f"#if ({ATP_GATE['hgatp']}) && UDB_VMID_WIDTH >= 2 && defined(UDB_SDTRIG_TEXTRA_MHSELECT_VMID_MATCH) "
            "&& UDB_SDTRIG_TEXTRA_MHVALUE_LEN > 0"
        ),
        *per_xlen(lambda g, _: guest_translation_setup(test_data, g, None, "VSmode")),
    ]
    for vmid_name, vmid in _VMIDS:
        lines.extend(
            [
                "#if __riscv_xlen == 64",
                f"LI(x{vmid_reg}, (0x3FFF << 44))",
                f"csrc hgatp, x{vmid_reg}",
                f"LI(x{vmid_reg}, ({vmid} << 44))",
                "#else",
                f"LI(x{vmid_reg}, (0x7F << 22))",
                f"csrc hgatp, x{vmid_reg}",
                f"LI(x{vmid_reg}, ({vmid} << 22))",
                "#endif",
                f"csrs hgatp, x{vmid_reg} # hgatp.VMID = {vmid_name} VMID",
                "hfence.gvma",
            ]
        )
        odd = vmid_name == "odd"
        for mode in GUESTS:
            lines.extend(_enter_guest(mode, temp_reg))
            for case, mhselect, flip in _mhselect_cases(odd):
                lines.extend(
                    _icount_textra_case(
                        test_data,
                        mode,
                        f"{mode.lower()}_{vmid_name}_{case.replace('sel1', 'sel2').replace('sel5', 'sel6')}",
                        coverpoint,
                        _mhselect_tdata3(cfg_reg, mhselect + 1, vmid, vmid, flip),
                        (cfg_reg, temp_reg),
                    )
                )
            lines.extend(_leave_guest(temp_reg))
    lines.extend([*guest_translation_teardown(test_data), "#endif // hgatp Sv39x4/Sv32x4, VMID textra match"])
    test_data.int_regs.return_registers([cfg_reg, temp_reg, vmid_reg])
    return lines


def _textra_asid_tests(test_data: TestData) -> list[str]:
    """sselect = 2 in VS-mode and VU-mode with vsatp = Sv39/Sv32 identity mapping the test image."""
    cfg_reg, temp_reg, asid_reg = test_data.int_regs.get_registers(3)
    coverpoint = "cp_textra_vsatp_asid"
    lines = [
        comment_banner(
            coverpoint,
            "textra sselect = 2: icount fires in VS-mode and VU-mode only when the low ASIDMAX bits of svalue\n"
            "equal vsatp.ASID = X (satp.ASID = 0).  vsatp identity maps the test image.  VU-mode cannot write\n"
            "the signature through that supervisor map, so its trap counts are signed in HS-mode",
        ),
        (
            f"#if ({ATP_GATE['vsatp']}) && UDB_ASID_WIDTH >= 2 && defined(UDB_SDTRIG_TEXTRA_SSELECT_ASID_MATCH) "
            "&& UDB_SDTRIG_TEXTRA_SVALUE_LEN >= UDB_ASID_WIDTH"
        ),
    ]
    for mode in GUESTS:
        priv_mode = f"{mode.upper()}mode"
        lines.extend(
            [
                *per_xlen(lambda _, vs, priv=priv_mode: guest_translation_setup(test_data, None, vs, priv)),
                "#if __riscv_xlen == 64",
                f"LI(x{asid_reg}, ({_ASID_X} << 44))",
                "#else",
                f"LI(x{asid_reg}, ({_ASID_X} << 22))",
                "#endif",
                f"csrs vsatp, x{asid_reg} # vsatp.ASID = X",
                "hfence.vvma",
                *_enter_guest(mode, temp_reg),
            ]
        )
        for case_name, sv, masked in _TEXTRA_ASID_CASES:
            sv64 = sv.replace("ASIDMAX", "16").replace("X", _ASID_X)
            sv32 = sv.replace("ASIDMAX", "9").replace("X", _ASID_X)
            tdata3 = _xlen_li_expr(
                cfg_reg,
                _textra_expr(32, sselect=2, svalue=_svalue(sv32), sbytemask=0x3 if masked else 0),
                _textra_expr(64, sselect=2, svalue=_svalue(sv64), sbytemask=0xF if masked else 0),
            )
            lines.extend(
                _icount_textra_case(
                    test_data,
                    mode,
                    f"{mode.lower()}_svalue_{case_name}",
                    coverpoint,
                    tdata3,
                    (cfg_reg, temp_reg),
                    sign_in_hs=mode == "Vu",
                )
            )
        lines.extend(_leave_guest(temp_reg))
        lines.extend(guest_translation_teardown(test_data))
    lines.append("#endif // vsatp Sv39/Sv32, ASID textra match")
    test_data.int_regs.return_registers([cfg_reg, temp_reg, asid_reg])
    return lines


def _hcontext_alias_tests(test_data: TestData) -> list[str]:
    """Write hcontext in HS-mode and M-mode and read it back through hcontext and mcontext."""
    covergroup = "SdtrigH_context_cg"
    rs, rd, mask = test_data.int_regs.get_registers(3)

    def check() -> list[str]:
        return [f"and x{rd}, x{rd}, x{mask} # implemented hcontext bits", write_sigupd(rd, test_data)]

    lines = [
        comment_banner(
            "cp_hcontext_hs, cp_hcontext_m",
            "hcontext is an alias of mcontext.  Write hcontext in HS-mode and read hcontext and mcontext; write\n"
            "mcontext and read hcontext in HS-mode; write hcontext in M-mode and read mcontext.  Reads are\n"
            "checked in the low UDB_DBG_HCONTEXT_WIDTH bits, because an implementation may tie upper bits to 0",
        ),
        "#ifdef UDB_HCONTEXT_IMPLEMENTED",
        f"LI(x{mask}, ((1 << UDB_DBG_HCONTEXT_WIDTH) - 1))",
    ]
    for name, value in (("ones", -1), ("random", random_int(14, signed=False))):
        lines.extend(
            [
                f"LI(x{rs}, {value})",
                _add_tc(test_data, f"csrw_{name}", "cp_hcontext_hs", covergroup),
                f"csrw hcontext, x{rs}",
                f"csrr x{rd}, hcontext",
                *check(),
                _csr_access(f"csrr x{rd}, mcontext # the hcontext field of mcontext", "S"),
                *check(),
            ]
        )
    lines.extend(
        [
            f"LI(x{rs}, {random_int(14, signed=False)})",
            _csr_access(f"csrw mcontext, x{rs}", "S"),
            _add_tc(test_data, "csrr_after_mcontext_write", "cp_hcontext_hs", covergroup),
            f"csrr x{rd}, hcontext",
            *check(),
            "RVTEST_TSBI_GOTO_MMODE",
            f"LI(x{rs}, {random_int(14, signed=False)})",
            _add_tc(test_data, "csrw", "cp_hcontext_m", covergroup),
            f"csrw hcontext, x{rs}",
            f"csrr x{rd}, mcontext",
            *check(),
            _add_tc(test_data, "csrr", "cp_hcontext_m", covergroup),
            f"csrr x{rd}, hcontext",
            *check(),
            "csrw mcontext, x0",
            "RVTEST_TSBI_GOTO_SMODE",
            "#endif // UDB_HCONTEXT_IMPLEMENTED",
        ]
    )
    test_data.int_regs.return_registers([rs, rd, mask])
    return lines


def _context_access_tests(test_data: TestData) -> list[str]:
    """Read scontext and hcontext in HS, VS and VU modes, with the boot stateen state and, with Smstateen, for each
    reachable (mstateen0.CONTEXT, hstateen0.CONTEXT).

    hcontext is accessible only in M and HS modes, so a guest access raises virtual instruction.  scontext is also
    accessible in VS-mode.  mstateen0.CONTEXT = 0 makes both illegal below M-mode, and hstateen0.CONTEXT = 0 makes a
    VS-mode scontext access raise virtual instruction.  Both bits are 1 afterwards, as at boot.
    """
    covergroup = "SdtrigH_context_cg"
    csrs = ["scontext", "hcontext"]
    lines = [
        comment_banner(
            "cp_context_access",
            "Read scontext and hcontext in HS, VS and VU modes.  hcontext raises virtual instruction in VS and VU;\n"
            "scontext does in VU",
        )
    ]
    for mode in ("hs", "vs", "vu"):
        lines.extend(read_in_mode(test_data, mode, csrs, mode, "cp_context_access", covergroup))
    lines.append("\n#ifdef SMSTATEEN_SUPPORTED")
    for mode in ("hs", "vs", "vu"):
        coverpoint = f"cp_{mode}_context_stateen"
        lines.append(
            comment_banner(
                coverpoint,
                f"Read scontext and hcontext in {mode.upper()}-mode for each reachable value of mstateen0.CONTEXT\n"
                "and hstateen0.CONTEXT.  Illegal instruction when mstateen0.CONTEXT = 0",
            )
        )
        for m, h in ((0, 0), (1, 0), (1, 1)):
            lines.extend(
                [
                    *mstateen0_bit(MSTATEEN0_CONTEXT, 1),
                    *hstateen0_bit(test_data, HSTATEEN0_CONTEXT, h),
                    *mstateen0_bit(MSTATEEN0_CONTEXT, m),
                    *read_in_mode(test_data, mode, csrs, f"m{m}_h{h}", coverpoint, covergroup),
                ]
            )
        lines.extend([*mstateen0_bit(MSTATEEN0_CONTEXT, 1), *hstateen0_bit(test_data, HSTATEEN0_CONTEXT, 1)])
    lines.append("#endif // SMSTATEEN_SUPPORTED")
    return lines


@add_priv_test_generator(
    "SdtrigH",
    required_extensions=["H", "Sdtrig"],
    march_extensions=["H"],
    extra_defines=[*SDTRIG_DEFINES, "#define BOOT_TO_SMODE"],
)
def make_sdtrigh(test_data: TestData) -> list[TestChunk]:
    """Generate tests for the SdtrigH suite."""
    seed(reproducible_hash("SdtrigH"))
    test_chunks: list[TestChunk] = []
    for mode in GUESTS:
        test_data.new_test_chunk(test_chunks, f"mode_bits_{mode.lower()}").code.extend(_mode_bit_tests(test_data, mode))
    test_data.new_test_chunk(test_chunks, "trap_triggers").code.extend(_trap_trigger_tests(test_data))
    test_data.new_test_chunk(test_chunks, "textra_mctx").code.extend(_textra_mctx_tests(test_data))
    test_data.new_test_chunk(test_chunks, "textra_vmid").code.extend(_textra_vmid_tests(test_data))
    test_data.new_test_chunk(test_chunks, "textra_asid").code.extend(_textra_asid_tests(test_data))
    test_data.new_test_chunk(test_chunks, "context").code.extend(
        [*_hcontext_alias_tests(test_data), *_context_access_tests(test_data)]
    )
    test_chunks.append(test_data.end_test_chunk())
    return test_chunks
