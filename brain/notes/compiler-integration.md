# Compiler integration context

The default language compiler and its declaration-resolution behavior remain compatible. The optional shipmbcompiler dependency is >=0.2.1,<0.3 on Python >=3.11. Direct compilation is selected explicitly; general and Roku are separate profiles. Core export is optional, and direct bytecode does not round-trip through Core or instruction IR.

General examples exercise list aggregation (27) and typed recursive factorial (720). The generic run adapter forwards compiler artifacts unchanged. Clarification and unsupported outcomes do not run or silently fall back. Memory captures source/outcomes locally, with explicit disable controls. Weather was a temporary build experiment and is not a product feature.

Remote-owned proprietary licensing, onboarding, and declaration-resolution fixes must be retained. Do not copy the older local package wholesale over this repository. Tests include the remote declaration-resolution suite, standalone pipeline tests, and both-order local wheel coinstallation. The broader language roadmap remains unfinished; this is implementation context, not a release claim.
