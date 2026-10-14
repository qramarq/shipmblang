# Contributor agreement setup

Status: pending. No CLA signing service or required check has been configured by
this change.

1. Choose the agreement terms for ZMachinery LLC: a contributor license grant or
   copyright assignment. A license grant does not transfer copyright.
2. Finalize the agreement text and publish the exact text in a GitHub Gist for
   CLA Assistant. Do not put private source code in the Gist.
3. Connect the intended repository at https://cla-assistant.io/ and select the
   agreement Gist. Configure each repository separately; keep the compiler
   repository private and preserve its proprietary license.
4. Verify the service can access the private compiler repository before relying
   on it there. If it cannot, record signed agreements through a private process
   and require maintainer verification before merging.
5. Test with a pull request from an unsigned contributor. Confirm the CLA check
   fails before signing and succeeds after signing, including all contributors.
6. Require the actual reported CLA status check in the repository's branch
   protection or ruleset. Installing the service alone does not block merges.
7. Replace the pending notice in CONTRIBUTING.md with the final agreement and
   signing links. Keep acceptance records and the agreement version accepted.

References:
- https://github.com/cla-assistant/cla-assistant
- https://apache.org/licenses/contributor-agreements.html
- https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

The public Python distribution declares `license = "Apache-2.0"` and includes
its license files. Modern Python packaging uses SPDX license expressions instead
of the deprecated `License ::` classifiers. The private compiler's license is
separate; repository visibility alone does not determine a software license.
