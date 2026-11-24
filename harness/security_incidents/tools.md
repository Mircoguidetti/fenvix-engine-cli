# tools.md: existing tools named in the incident sources

Desk research, all URLs accessed **2026-11-24**. Eight tools: those named most in the incident write-ups
(`incidents.csv`) plus the ones the write-ups compare against.

**How each fact was obtained (read this first).** The vendor sites could not be opened from this session:
WebFetch returned `getaddrinfo ENOTFOUND <host>` and `curl` through the session proxy returned
`CONNECT tunnel failed, response 403` for stepsecurity.io, socket.dev, aikido.dev, snyk.io, gitguardian.com,
endorlabs.com and wiz.io (network policy of this container). GitHub pages did open. So:
* **[page]** = read on the page itself (GitHub READMEs);
* **[snippet]** = taken from the search engine's summary of the vendor page, not read on the page. Prices marked
  [snippet] are unverified and may be stale;
* **[3rd]** = a third-party page (AWS Marketplace, Vendr, G2), also [snippet] unless stated.

| # | tool | what it watches | compares before/after a change? | sells to (as stated) | public price | sources (accessed 2026-11-24) |
|---|---|---|---|---|---|---|
| 1 | StepSecurity Harden-Runner | job-level network egress on the CI runner, plus file and process activity; can block egress [page] | **yes**: a per-job baseline of past outbound connections; "any future outbound calls not in the baseline trigger a detection" (Community tier) [page] | Community (free, public repos) and Enterprise (paid) tiers; claims users "Microsoft, Google, CISA, DataDog, Intel" [snippet] | Community $0 (run cap); Enterprise per contributing developer, quote only [snippet]; AWS Marketplace line $192/developer [3rd] | https://github.com/step-security/harden-runner [page]; https://www.stepsecurity.io/pricing (ENOTFOUND; [snippet]); https://aws.amazon.com/marketplace/pp/prodview-maeh2xznigdi4 [3rd] |
| 2 | Socket | static package scan: install scripts, network / filesystem / shell / env API use, obfuscation; install wrapper and firewall | **yes, at dependency level**: a pull-request comment for any dependency added, updated or removed, alerting on new install scripts and new capabilities [snippet] | "the best security teams in the world use Socket", "27,000+ orgs" [snippet] | Free $0; Team $25/dev/month; Business $50/dev/month; Enterprise custom [snippet] | https://github.com/SocketDev/socket-cli [page]; https://socket.dev/pricing (ENOTFOUND; [snippet]); https://docs.socket.dev/docs/socket-for-github [snippet] |
| 3 | Aikido Security (Safe Chain, malware feed) | install time: a local proxy that checks npm/PyPI downloads against a malware feed and blocks packages younger than 48 h by default [page]; the wider platform does SAST/SCA/secrets | no behaviour comparison (an age gate only; INFERRED) | "Block malware on developer laptops and CI/CD" [page]; a startups page [snippet] | Safe Chain free [page]; platform Free / Basic $350 / Pro $700 / Advanced $1,050 per month, figures conflict between snapshots [snippet] | https://github.com/AikidoSec/safe-chain [page]; https://www.aikido.dev/pricing (ENOTFOUND; [snippet]); https://www.g2.com/products/aikido-security/pricing [3rd] |
| 4 | Snyk | static scan of dependencies against a vulnerability and malicious-package database; SAST | partly: new pull requests are checked against the database; no behaviour baseline [snippet] | priced per contributing developer; Ignite for smaller organisations [snippet] | Free $0; Team from $25/contributing dev/month; Ignite from $1,260/dev/year; Enterprise custom [snippet] | https://snyk.io/plans/ (ENOTFOUND); https://snyk.io/pricing/ [snippet] |
| 5 | GitGuardian | secrets in code, commits, CI logs, public GitHub | incremental only (each commit since the last build); no behaviour baseline [snippet] | developers and "Security Teams" [snippet] | Free up to 25 developers; Business / Enterprise contact sales [snippet]; AWS $5,500/year for 25 developers [3rd] | https://www.gitguardian.com/pricing (ENOTFOUND; [snippet]); https://aws.amazon.com/marketplace/pp/prodview-kvxvjes3oy7dq [3rd] |
| 6 | Endor Labs | static malware and code-analysis rules over new npm/PyPI packages; package firewall | no behaviour diff found; pull-request scans through its GitHub App [snippet] | "organizations that value developer experience" [snippet] | not public (per code contributor per year; AWS listings $7,200 and $12,960 for 10 contributors/year [3rd]) | https://www.endorlabs.com/pricing (ENOTFOUND); https://docs.endorlabs.com/introduction/malware-detection/ [snippet] |
| 7 | Datadog GuardDog | static scan of package source (YARA, Semgrep) and registry metadata; flags install scripts [page] | no: scans one version at a time; a `risky_new_dependency` risk-score rule only [page] | open source (Apache-2.0), for CI pipelines and Datadog Cloud SIEM [page] | free [page] | https://github.com/DataDog/guarddog [page] |
| 8 | Wiz (Wiz Code, Sensor, Defend) | static scan of code and CI/CD pipelines; eBPF runtime sensor on workloads (not per CI job; INFERRED) | none found | cloud security for organisations, quote only [snippet] | not public; AWS listings e.g. 100 Wiz Code licences $58,500/12 months [3rd] | https://www.wiz.io/blog/shai-hulud-2-0-ongoing-supply-chain-attack (ENOTFOUND from curl; seen via search); https://underdefense.com/industry-pricings/wiz-pricing-ultimate-guide-for-security-products/ [3rd] |

Also seen, not counted in the eight: OpenSSF package-analysis (runs packages in a gVisor sandbox and records files,
addresses and commands; "tracks changes in how packages behave over time"; free, public BigQuery dataset) [page:
https://github.com/ossf/package-analysis].

## What none of them does (the gap the research asks about)

Harden-Runner is the only tool that publicly documents a behaviour baseline per change, and it works per CI job: it
does not know which test or which import made a connection. Socket compares at dependency level (what a new version
*could* do: static capabilities), not what it *did* when run. The others scan statically against known lists or look
for leaked secrets. No source found describes a per-test before/after record of env reads, files, connections and
children. That is fenvix's angle. This is a claim from these sources only, not a market survey.
