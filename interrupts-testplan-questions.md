# Interrupts test plan: questions and decisions taken (2026-08-29)

Decisions I made while implementing the plan in
https://docs.google.com/spreadsheets/d/1gBymMadMSRy4SW_nYUmglFAe1-LtjaqOA6aXcrxCAsk; each needs a yes/no
or a correction. Rows are worked in plan order; the status of each row is at the end.

## Framework / environment

1. **Where "old" lives.** The retired suites went to a top-level `old/` tree mirroring their paths
   (`old/generators/...`, `old/coverpoints/priv`, `old/coverpoints/norm`, `old/tests/priv`). A directory
   under `tests/priv/` or under `generators/.../extensions/` would still be found by act's
   `rglob("*/<suite>/*.S")` and by the generator discovery, so `old/` sits outside all of them. OK?
2. **Temporary interrupt parameters.** Platform sources are declared per DUT in `rvmodel_macros.h` as
   `UDB_MTI_SUPPORTED`, `UDB_MSI_SUPPORTED`, `UDB_MEI_SUPPORTED`, `UDB_SEI_SUPPORTED`, `UDB_LCOFI_SUPPORTED`
   (LCOFI = "a software write to mip.LCOFIP raises the interrupt"); `tests/env/derived_config.h/.svh` derive
   `UDB_STI/SSI_SUPPORTED` from `S_SUPPORTED`, drop SEI/LCOFI without S or Sscofpmf, and derive
   `UDB_<TYPE>_DELEGATION_SUPPORTED` = supported && S. The platform ones are mirrored into
   `rvmodel_macros.svh` for coverage. The headers are shared through symlinks between rv32/rv64 and between
   profile configs, which is why only platform facts can live there. Names deliberately match the plan so
   the generators do not change when UDB provides them. Do you want a per-DUT delegation parameter
   (a DUT that hardwires some `mideleg` bits) now, or is derived delegation enough until UDB has it?
3. **Imperas** keeps the `nop` `RVMODEL_SET/CLR_MEXT/SEXT_INT` macros because `check_defines.h` insists they
   exist; `UDB_MEI/SEI_SUPPORTED` are simply not defined there, so MEI/SEI testcases compile out. OK?
4. **QEMU and LCOFI.** QEMU accepts a write to `mip.LCOFIP` (it reads back) but never raises the interrupt,
   and `sip.LCOFIP` reads 0. QEMU's header therefore omits `UDB_LCOFI_SUPPORTED`. Is a software write to
   `mip.LCOFIP` the intended way to raise LCOFI (a real counter overflow is not producible on Sail)?
5. **CVW `RVMODEL_SET_SSW_INT`** wrote `CLINT+0xC000` (trickbox SSIP), which the rv64gc/rv32gc builds do not
   instantiate, so `mip.SSIP` never became pending. I removed the SSW macros from the cvw header (falls
   back to `mip.SSIP`). Confirm, or point me at the trickbox mapping.
6. **STI clearing in the trap handler.** `RVTEST_CLR_STIMER_INT` used to be empty; the handler now clears
   `mip.STIP` and disarms `stimecmp` (through T-SBI from an S-mode handler; `stimecmph`/`menvcfgh` were
   added to `tsbi_instr_table` for RV32). This changes the environment for every suite that takes an STI
   (Zawrs*, S, ...); regression results are in the status section.
7. **Trap count is not usable as a signature value**: the reference ELF is built with `-DSIGNATURE` and
   `tests/env/sail_macros.h` replaces the platform macros with Sail magic stores, so the DUT and reference
   take different numbers of T-SBI ecalls. Each testcase instead records the interrupt's pending bit after
   waiting (`mip` in M, `sip` in S, `sip` through T-SBI in U); taken interrupts are recorded by the handler.
   OK?
8. **Vectored proof.** The handler already writes the compressed vector-entry offset into trap-record
   word 0 (bits 10:6), so vectored entry is checked by the signature without extra code. Does that satisfy
   the "*** way to leave a special signature on vectored interrupts" note?
9. **Handler disables the taken interrupt's xIE bit.** Kept as is; every testcase rewrites `mie`/`sie`.
   Should the handler stop clearing xIE now that it always clears the source?
10. **Normative rules.** `coverpoints/norm/InterruptsSm.yaml` and `InterruptsS.yaml` were produced by
    mapping the old rule references onto the new coverpoints by keyword (trigger/enable/priority/wfi).
    They need a real pass once the rows exist.

11. **Wally bug found by cp_priority_mideleg (CVW fails InterruptsSm on both XLENs).** With `mideleg = 0x2`
    the S-mode handler executes `csrrc x9, sie, 0x2`; ImperasDV clears only SSIE but Wally also clears
    the non-delegated SEIE/STIE in `mie`. `src/privileged/csri.sv:85` writes
    `MIE_REGW <= (val & 0x222 & MIDELEG) | (MIE_REGW & 0x888)`, dropping `MIE_REGW & 0x222 & ~MIDELEG`
    (writes to non-delegated `sie` bits must be ignored; `sie.LCOFIE`, bit 13, is not handled either).
    InterruptsS passes on CVW because it never partially delegates.
12. **Imperas rv32 `sail.json`** had `Sscofpmf: supported=false` while the UDB yaml and `imperas.ic`
    enable it, so the reference never raised LCOFI and the new poll-for-pending loop hung the reference
    run (300 s timeout). Set to true in `imperas-rv32gck` and `imperas-rv32gcv` to match rv64-max.

## cp_trigger (row 1)

11. The plan's S-mode expectation ("pending if supported, trap if SIE = 1") only holds for delegated
    supervisor interrupts. Machine-level interrupts, and supervisor interrupts with `mideleg`=0, trap to
    M-mode from S-mode regardless of SIE. The tests follow the architecture (verified: 120 Sm and 32 S
    testcases behave exactly as expected on spike). Confirm the coverage cross should stay
    `SIE x mideleg x type` (no bins removed).
12. `mstatus.MIE` while a testcase runs in S or U mode is not specified; the tests set it to 1.
13. In U-mode SIE has no effect (supervisor interrupts are always enabled below S). "Same as S" keeps
    SIE={0,1} for U; dropping it would halve the U testcases.
14. `mideleg = 1s` is written as all ones (WARL); coverage keys on each interrupt's own `mideleg` bit, and
    machine-level interrupts only have a `mideleg`=0 bin.
15. `stvec.MODE` for the S/U rows of InterruptsSm is written from M-mode (stvec is M-accessible). OK?
16. The coverage model has no trap entries (the Sail-to-RVVI converter drops them), so a taken interrupt is
    recognized at the handler's first instruction (`csrrw sp, xscratch, sp`) from the post-trap xcause and
    xPP/xPIE, and a masked one at a `addi x0, x0, 1` sample point after the wait. Both count as
    "observed"; taken-vs-masked is verified by the signature, not by coverage.

## Later rows (open before I implement them)

17. cp_trigger_reg: M-mode writes `mip.SSIP`/`mip.SEIP` directly; S-mode writes `sip.SSIP` directly and
    `mip.SSIP`/`mip.SEIP` through T-SBI; U-mode writes all three through T-SBI. Is that the intended set?
18. cp_enable: for the S/U rows "walking 1s in mie" is read as walking 1s in `sie` with all supervisor
    interrupts delegated (otherwise `sie` has no effect).
19. cp_priority_*: with two interrupts pending and both enabled, the handler clears the first and the second
    is taken immediately after `mret`; both trap records are kept in order as the priority evidence.
    Two platform facts shaped the implementation: (a) after raising the sources the test idles once
    (`RVTEST_IDLE_FOR_INTERRUPT`) before enabling, otherwise spike's PLIC has not yet raised MEIP/SEIP when
    the first trap records `mip`; (b) sources are raised in cause order (SEI before MEI) because spike's
    PLIC feeds both contexts from one UART source and only raises the context that was enabled first --
    `cp_priority_mie` raised MEI before SEI and SEIP never appeared. Is raising MEI and SEI together
    (through one PLIC source) something the plan wants, or should MEI/SEI pairs be excluded?
    S/U rows use `mideleg = 1s`; in `cp_priority_mideleg` exactly one of the pair is delegated (only
    supervisor-level interrupts can be), so pairs of two machine-level interrupts have no bin there.
    (c) The SEI+MEI pair is skipped on platforms that declare `RVMODEL_SEXT_MEXT_SHARED_SOURCE`
    (spike, QEMU, CVW: one UART source drives both PLIC contexts). Clearing MEI there disables the
    source, which drops SEIP on a level-sensitive PLIC (QEMU, CVW) but not on spike's latched one nor
    on Sail's generator, so the pair has no single expected sequence. The same define now gates the
    trap handler's "MEIP pending: only clear mip.SEIP" guard; without it whisper's APLIC-driven SEIP
    (delivered through `mvip`) was cleared by that `csrc mip` while Sail's generator stayed asserted.
    Is a platform define the right place for this, or should MEI/SEI pairs be dropped from the plan?
20. cp_wfi in U-mode: spike raises illegal-instruction for WFI in U-mode while Sail waits for the timer;
    the priv spec allows both ("executing WFI in U-mode causes an illegal-instruction exception unless it
    completes within an implementation-specific bounded time"), so the U-mode row was dropped from
    cp_wfi in both suites (S-mode and M-mode rows remain). OK to leave U out?
21. cp_wfi_timeout: the WFI timeout is implementation-defined. Sail, spike, whisper, QEMU and Imperas all
    trap illegal-instruction immediately and pass; CVW under Questa lockstep fails because ImperasDV
    retires the WFI where Wally traps (pre-existing, same as the old wfi_timeout tests). The row is kept
    and CVW is checked without lockstep (see status).
22. cp_wfi timing: the timer must be armed before hopping to the lower mode with a longer delay (8x for
    M-mode arming, 16x when S-mode arms stimecmp through T-SBI mtime reads) so that it does not fire
    inside the T-SBI stubs before WFI; the loop repeats WFI until a trap is taken (or, where the mode
    cannot take it, until the pending bit shows). Delays are multiples of RVMODEL_TIMER_INT_SOON_DELAY.

## Status (2026-08-29, end of the unattended run)

All nine rows of both tabs are implemented (`InterruptsSm`: 571 testcases, `InterruptsS`: 130 testcases),
with coverpoints in `coverpoints/priv/Interrupts{Sm,S}_coverage.svh` and normative-rule maps in
`coverpoints/norm/Interrupts{Sm,S}.yaml`. Every row was validated on spike first (trace audit: each testcase
takes exactly the interrupts, in the mode, that the architecture predicts), then on the other models.

| Config                                         | InterruptsSm | InterruptsS           | Notes                                                                       |
| ---------------------------------------------- | ------------ | --------------------- | --------------------------------------------------------------------------- |
| sail-rv64-max / rv32-max (coverage)            | 100%         | 100%                  | both covergroups, both XLENs                                                |
| spike-rv64-max / rv32-max                      | pass         | pass                  |                                                                             |
| whisper-rv64-max / rv32-max                    | pass         | pass                  | needed `RVMODEL_SEXT_MEXT_SHARED_SOURCE` gating (q.19c)                     |
| qemu-rv64-max / rv32-max                       | pass         | pass                  | LCOFI compiled out (q.4)                                                    |
| imperas-rv64-max                               | pass         | pass                  | MEI/SEI compiled out (q.3)                                                  |
| imperas-rv32gck / rv32gcv                      | pass         | pass                  | after `sail.json` Sscofpmf and `imperas.ic` overrides (q.23, quantum)       |
| cvw-rv64gc / rv32gc (Questa lockstep)          | FAIL         | rv64 FAIL / rv32 pass | Sm: Wally `sie` bug (q.22); S rv64: lockstep WFI-timeout discrepancy (q.21) |
| cvw-rv64gc / rv32gc (Verilator, self-checking) | pass         | pass                  | the `sie` bug is invisible to the signature; only lockstep catches it       |

Rows and testcase counts (InterruptsSm / InterruptsS): cp_trigger 132 / 32, cp_trigger_reg 56 / 24,
cp_trigger_sti_sstc 24 / 8, cp_enable 147 / 32, cp_priority_mip 63 / 12, cp_priority_mie 63 / 12,
cp_priority_mideleg 72 / -, cp_wfi 6 / 2, cp_wfi_timeout 8 / 8.

Environment changes made on the way (all uncommitted on `tsbiintu`): `old/` tree; `UDB_*_SUPPORTED`
blocks in every platform header (Imperas without MEI/SEI, QEMU without LCOFI) plus
`RVMODEL_SEXT_MEXT_SHARED_SOURCE` on spike/QEMU/CVW; `tests/env/interrupt_config.h` (derived STI/SSI/
delegation), `derived_config.svh`, `dut_macros.py` mirroring; `RVTEST_SET/CLR_LCOF_INT_{M,S,U}` macros
and stubs; trap handler: `clr_Lcof_int`, real STI clearing, correctly encoded default dispatch entries
for causes 12-23, shared-source guard; `tsbi_instr_table` gained `menvcfgh` and `stimecmph`; CVW header
lost its dead SSW macros; Imperas rv32 `sail.json`/`imperas.ic` fixes; docs (`interrupts.adoc`,
`profiles.adoc`), Imperas `ci.yaml`, AGENTS.md notes.

Regression of the other suites that use the changed handler paths (ZawrsS/Sm/U, S, Sm, ExceptionsS/U, Smstateen)
on spike-rv64-max: 45/46 pass; the one failure is `Smstateen cp_walking_ones mstateen0_set_bit_60`
(spike keeps mstateen0 bit 60 writable, Sail does not) -- a CSR readback unrelated to interrupts and
already listed as a Sail gap in `config/imperas/ci.yaml`.
