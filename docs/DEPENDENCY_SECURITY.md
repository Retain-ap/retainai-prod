# Dependency checks

The required backend CI job now runs `pip-audit` against `backend/requirements.txt` on Linux using the same Python 3.12 job runtime as the regression tests. The scanner is pinned to 2.10.1 and installed into a separate temporary virtual environment, so it does not change the application's test dependencies. `--strict` rejects dependency-collection failures; vulnerability-service errors and findings also fail the command. No automatic upgrade, ignore list or `continue-on-error` is used.

This audits the dependency set resolved from the requirements on that run. It is not a frozen inventory of an already-running Render instance: several transitive dependencies and two top-level ranges remain unpinned. A deployment still needs its exact release and health checks verified. A successful audit means no findings in the queried vulnerability database at that time, not that every package is proven secure.

The frontend CI separately checks production dependencies at moderate severity and above, and development tools at critical severity. On November 13, PR68 updated compatible development dependencies Express, qs and node-forge, reducing the full frontend audit from 37 to 34 findings (16 low, 5 moderate, 13 high, zero critical); the production audit remained zero. The remaining Create React App chains need a planned toolchain migration or compatible upstream fixes. Do not use the misleading `react-scripts@0.0.0` major audit fix or override incompatible dependency majors to make the count disappear.

A separate Windows/Python 3.13 requirements audit found zero known vulnerabilities across 46 resolved backend dependencies on November 13. Linux CI is the acceptance check for this workflow change; that Windows result alone does not establish the deployed environment's inventory.

## Ongoing security update proposals

The default branch's .github/dependabot.yml configures security-only proposals. The zero open-pull-requests-limit disables routine version-update PRs, not security fixes. Minor and patch security fixes are grouped per ecosystem; necessary major fixes remain individual proposals for review. No target branch, automatic merge, deploy, privileged workflow, private registry credential or larger runner is configured. Security checks still need to pass before any dependency update is accepted.

Repository dependency alerts and security-update settings must also be enabled; the YAML alone does not enable them. Record the provider setting verification in the dated release log. GitHub can open security proposals immediately after enablement and has a separate security-PR limit. The weekly schedule is required configuration metadata, not a promise that security checks happen only weekly.

Reference: [GitHub security-update configuration](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-security-updates).
