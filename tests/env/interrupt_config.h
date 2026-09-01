# interrupt_config.h
# Interrupt support parameters derived from the DUT platform header and the ISA configuration
# David Harris david_harris@hmc.edu August 2026
# SPDX-License-Identifier: Apache-2.0

#ifndef INTERRUPT_CONFIG_H
#define INTERRUPT_CONFIG_H

// Temporary interrupt support parameters until UDB provides them. Included after rvmodel_macros.h.
// Platform sources (UDB_MTI/MSI/MEI/SEI/LCOFI_SUPPORTED) come from the DUT's rvmodel_macros.h;
// the supervisor-level sources also require the ISA configuration to support them.
#if defined(S_SUPPORTED)
  #define UDB_STI_SUPPORTED 1
  #define UDB_SSI_SUPPORTED 1
  #if !defined(SSCOFPMF_SUPPORTED)
    #undef UDB_LCOFI_SUPPORTED
  #endif
  #define UDB_STI_DELEGATION_SUPPORTED 1
  #define UDB_SSI_DELEGATION_SUPPORTED 1
  #if defined(UDB_SEI_SUPPORTED)
    #define UDB_SEI_DELEGATION_SUPPORTED 1
  #endif
  #if defined(UDB_LCOFI_SUPPORTED)
    #define UDB_LCOFI_DELEGATION_SUPPORTED 1
  #endif
#else
  #undef UDB_SEI_SUPPORTED
  #undef UDB_LCOFI_SUPPORTED
#endif

#endif // INTERRUPT_CONFIG_H
