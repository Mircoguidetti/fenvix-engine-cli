# queries.md: search log

Every query of the desk research, 2026-11-24. Web searches were run by four research sub-agents (WebSearch) and by
the work session (GitHub issue search through `gh api search/issues`, used to date `disclosed_url` pages).
`ok` = the query returned results (even when none was relevant); `failed` = the query returned an error (quoted).
Families: F1-F5 are the required families (spec section 5); `Further: ...` families come from the references of
sources found; `Tools` feeds tools.md; `Verify` dates the disclosed pages.

Totals: 180 queries, 176 ok, 4 failed (failed share 2%: below one half, so no BLOCKED verdict).

Stopped by: the 'two consecutive further families add no new counted incident' rule, in each of the three incident
streams. npm stream: the families 'npm supply chain attack October 2026' / 'npm worm November 2026' and 'npm malicious
package September 2026 CI secrets' added nothing new. PyPI stream: 'GitGuardian round-up' then 'Checkmarx/Zscaler 2025'.
Actions/agents stream: 'Okta/Trend TeamPCP list' then 'StepSecurity incident list Oct/Nov 2026'. The 4-hour cap was not
reached (all searches ran within about 10 minutes of wall-clock time, in parallel).

## Page fetches that failed (not queries; listed per rule 6)

The container's network policy refuses most vendor hosts. WebFetch: `getaddrinfo ENOTFOUND <host>`; curl through the
session proxy: `CONNECT tunnel failed, response 403`. Refused: stepsecurity.io, www.stepsecurity.io, docs.stepsecurity.io,
socket.dev, www.aikido.dev, snyk.io, www.gitguardian.com, blog.gitguardian.com, www.endorlabs.com, www.wiz.io,
thehackernews.com, krebsonsecurity.com, unit42.paloaltonetworks.com, www.cisa.gov, blog.pypi.org, research.jfrog.com,
k-reel.github.io, openwall.com. Opened: securitylabs.datadoghq.com, github.com (advisories, issues, READMEs), github.blog, nx.dev.
Consequence: dates and facts from refused hosts come from search-result summaries, not from the pages (see REPORT.md).

| # | family | query | date | status | note |
|---|---|---|---|---|---|
| Q1 | F1 | npm malware stealing CI secrets 2025 | 2026-11-24 | ok |  |
| Q2 | F1 | npm malicious package environment variables exfiltration 2025 | 2026-11-24 | ok |  |
| Q3 | F1 | npm package steals GitHub token CI 2026 | 2026-11-24 | ok |  |
| Q4 | F1 | Sonatype country-currency-map hijacked | 2026-11-24 | ok |  |
| Q5 | F1 | @acitons/artifact typosquat | 2026-11-24 | ok |  |
| Q6 | F1 | eslint-config-prettier is package compromise | 2026-11-24 | ok |  |
| Q7 | F1 | npm supply chain attack October 2026 | 2026-11-24 | ok |  |
| Q8 | F1 | npm malicious package September 2026 CI secrets | 2026-11-24 | ok |  |
| Q9 | F1 | typosquatted npm packages OpenSearch Elasticsearch | 2026-11-24 | ok |  |
| Q10 | F1 | Sonatype sbx-mask | 2026-11-24 | ok | returned results, nothing relevant |
| Q11 | F2 | tj-actions/changed-files CVE-2025-30066 compromise memory dump secrets | 2026-11-24 | ok |  |
| Q12 | F2 | reviewdog/action-setup CVE-2025-30154 compromise | 2026-11-24 | ok |  |
| Q13 | F2 | GhostAction campaign GitGuardian secrets exfiltrated workflows | 2026-11-24 | ok |  |
| Q14 | F2 | StepSecurity tj-actions Runner.Worker memory gist memdump.py | 2026-11-24 | ok |  |
| Q15 | F2 | GhostAction GitGuardian September 5 2025 FastUUID | 2026-11-24 | ok |  |
| Q16 | F2 | Wiz reviewdog action-setup March 2025 install.sh base64 | 2026-11-24 | ok |  |
| Q17 | F2 | trivy-action setup-trivy compromise 2026 secrets stolen TeamPCP | 2026-11-24 | ok |  |
| Q18 | F2 | Checkmarx KICS GitHub Action compromised 2026 | 2026-11-24 | ok |  |
| Q19 | F2 | Nx s1ngularity root cause pull_request_target GHSA-cxm3-wv7p-598c | 2026-11-24 | ok |  |
| Q20 | F2 | hackerbot-claw pull_request_target Trivy February 2026 PAT | 2026-11-24 | ok |  |
| Q21 | F2 | LiteLLM PyPI .pth TeamPCP March 2026 exfil domain | 2026-11-24 | ok |  |
| Q22 | F2 | Trivy Runner.Worker memory scan.aquasecurtiy.org GHSA | 2026-11-24 | ok |  |
| Q23 | F2 | Nx s1ngularity telemetry.js postinstall CI behavior AI CLI | 2026-11-24 | ok |  |
| Q24 | F2 | Grafana pwn request pull_request_target April 2025 | 2026-11-24 | ok |  |
| Q25 | F2 | Grafana May 2026 GitHub token stolen CoinbaseCartel | 2026-11-24 | ok |  |
| Q26 | F2 | PostHog Shai-Hulud 2.0 post-mortem pull_request_target | 2026-11-24 | ok |  |
| Q27 | F2 | Unit 42 spotbugs pull_request_target PAT root cause | 2026-11-24 | ok |  |
| Q28 | F2 | GitHub Action compromised tag repointed credential stealer 2026 -trivy -kics | 2026-11-24 | ok |  |
| Q29 | F2 | actions-cool/issues-helper compromised May 18 2026 | 2026-11-24 | ok |  |
| Q30 | F2 | codfish/semantic-release-action compromised Miasma | 2026-11-24 | ok |  |
| Q31 | F2 | xygeni-action compromised GitHub Action 2026 tag | 2026-11-24 | ok |  |
| Q32 | F2 | hackerbot-claw Trivy apidiff workflow PAT exfiltrated to which host | 2026-11-24 | ok |  |
| Q33 | F2 | Kong Ingress Controller compromise January 2025 | 2026-11-24 | ok |  |
| Q34 | F3 | PyPI malicious packages exfiltrating environment variables 2025-2026 | 2026-11-24 | ok |  |
| Q35 | F3 | LiteLLM PyPI compromise 2026 TeamPCP .pth | 2026-11-24 | ok |  |
| Q36 | F3 | chimera-sandbox-extensions JFrog | 2026-11-24 | ok |  |
| Q37 | F3 | telnyx PyPI compromise 2026 | 2026-11-24 | ok |  |
| Q38 | F3 | litellm 1.82.8 litellm_init.pth subprocess.Popen base64 python -c exfiltration models.litellm.cloud | 2026-11-24 | ok |  |
| Q39 | F3 | telnyx 4.87.2 _client.py WAV steganography payload Windows Linux exfiltration domain TeamPCP | 2026-11-24 | ok |  |
| Q40 | F3 | telnyx _client.py malicious subprocess.Popen sys.executable detached start_new_session Linux payload | 2026-11-24 | ok |  |
| Q41 | F3 | litellm proxy_server.py 1.82.7 malicious code import-time subprocess payload kubernetes secrets TeamPCP analysis | 2026-11-24 | ok |  |
| Q42 | F3 | chimera-sandbox-extensions malicious PyPI JFrog June 2025 domain generation algorithm AWS tokens CI/CD exfiltration | 2026-11-24 | ok |  |
| Q43 | F3 | PyPI token phishing compromise 2025 num2words | 2026-11-24 | ok |  |
| Q44 | F3 | PyPI GitHub Actions token exfiltration 2025 | 2026-11-24 | ok |  |
| Q45 | F3 | PyPI package steals AWS credentials CI/CD 2025 | 2026-11-24 | ok |  |
| Q46 | F3 | PyPI malicious package import time credential stealer 2026 | 2026-11-24 | ok |  |
| Q47 | F3 | num2words 0.5.15 malicious payload Scavenger what did it steal | 2026-11-24 | ok |  |
| Q48 | F3 | chimera-sandbox-extensions check_update function DGA second stage Python stealer JAMF executed when | 2026-11-24 | ok |  |
| Q49 | F3 | litellm_init.pth payload reads ~/.aws/credentials tpcp.tar.gz X-Filename | 2026-11-24 | ok |  |
| Q50 | F3 | litellm GitHub issue 24512 March 24 2026 first report fork bomb | 2026-11-24 | ok | returned results, no hit for #24512 |
| Q51 | F4 | Shai-Hulud npm worm trufflehog credentials exfiltration | 2026-11-24 | ok |  |
| Q52 | F4 | Shai-Hulud 2.0 Second Coming preinstall bun setup_bun.js | 2026-11-24 | ok |  |
| Q53 | F4 | s1ngularity Nx compromise telemetry.js | 2026-11-24 | ok |  |
| Q54 | F4 | Shai-Hulud September 2025 bundle.js webhook.site | 2026-11-24 | ok |  |
| Q55 | F4 | Shai-Hulud worm analysis GITHUB_ACTIONS trufflehog | 2026-11-24 | ok |  |
| Q56 | F4 | PhantomRaven Koi Security | 2026-11-24 | ok |  |
| Q57 | F4 | SANDWORM_MODE npm worm Socket 2026 | 2026-11-24 | ok |  |
| Q58 | F4 | Shai-Hulud 2.0 bun_environment.js CI detached | 2026-11-24 | ok |  |
| Q59 | F4 | Shai-Hulud first wave GITHUB_ACTIONS condition | 2026-11-24 | ok |  |
| Q60 | F4 | npm worm November 2026 compromised packages tokens | 2026-11-24 | ok |  |
| Q61 | F5 | PromptPwnd Aikido prompt injection GitHub Actions AI agents secrets Gemini CLI | 2026-11-24 | ok |  |
| Q62 | F5 | Clinejection Cline GitHub Actions prompt injection issue triage npm token 2026 | 2026-11-24 | ok |  |
| Q63 | F5 | Amazon Q Developer VS Code extension malicious prompt wiper July 2025 | 2026-11-24 | ok |  |
| Q64 | F5 | claude-code-action prompt injection GitHub issue exfiltrate secrets real attack 2026 | 2026-11-24 | ok |  |
| Q65 | F5 | AI coding agent GitHub Actions prompt injection exploited in the wild token exfiltrated 2026 | 2026-11-24 | ok |  |
| Q66 | F5 | run-gemini-cli GitHub Action vulnerability prompt injection GHSA 2025 | 2026-11-24 | ok |  |
| Q67 | F5 | Clinejection adnanthekhan February 9 2026 cacheract | 2026-11-24 | ok |  |
| Q68 | F5 | Cline incident unknown actor post-mortem GHSA | 2026-11-24 | ok |  |
| Q69 | F5 | Wiz CodeBreach AWS CodeBuild | 2026-11-24 | ok |  |
| Q70 | Further: PhantomRaven | PhantomRaven payload preinstall packages.storeartifact.com | 2026-11-24 | ok |  |
| Q71 | Further: SANDWORM_MODE | SANDWORM_MODE Socket analysis on import | 2026-11-24 | ok |  |
| Q72 | Further: TeamPCP / Bitwarden | Bitwarden CLI 2026.4.0 | 2026-11-24 | ok |  |
| Q73 | Further: TeamPCP / Bitwarden | Bitwarden CLI npm compromise Socket Third Coming | 2026-11-24 | ok |  |
| Q74 | Further: TeamPCP / Bitwarden | elementary-data TeamPCP | 2026-11-24 | ok |  |
| Q75 | Further: TeamPCP / Bitwarden | Bitwarden CLI npm April 2026 | 2026-11-24 | ok |  |
| Q76 | Further: Mini Shai-Hulud | @7nohe/openapi-react-query-codegen | 2026-11-24 | ok |  |
| Q77 | Further: Mini Shai-Hulud | safedep Mini Shai-Hulud Strikes Again 317 | 2026-11-24 | ok |  |
| Q78 | Further: Mini Shai-Hulud | TanStack mini Shai-Hulud OIDC | 2026-11-24 | ok |  |
| Q79 | Further: Mini Shai-Hulud | Mini Shai-Hulud TanStack payload Session | 2026-11-24 | ok |  |
| Q80 | Further: Mini Shai-Hulud | Mini Shai-Hulud PyPI | 2026-11-24 | ok |  |
| Q81 | Further: Mini Shai-Hulud | mistralai 2.4.6 guardrails-ai | 2026-11-24 | ok |  |
| Q82 | Further: CanisterWorm | safedep @fairwords npm credential worm | 2026-11-24 | ok |  |
| Q83 | Further: CanisterWorm | namastex npm packages compromised CanisterWorm | 2026-11-24 | ok |  |
| Q84 | Further: Miasma | ReversingLabs npm binding.gyp CI/CD secrets | 2026-11-24 | ok |  |
| Q85 | Further: Miasma | Miasma worm Runner secrets | 2026-11-24 | ok |  |
| Q86 | Further: Miasma | Miasma pyphetools | 2026-11-24 | ok |  |
| Q87 | Further: Miasma | Hades campaign PyPI | 2026-11-24 | ok |  |
| Q88 | Further: Miasma | Hades .pth CI check | 2026-11-24 | ok |  |
| Q89 | Further: jscrambler / AsyncAPI | jscrambler npm compromise July 2026 | 2026-11-24 | ok |  |
| Q90 | Further: jscrambler / AsyncAPI | npm ecosystem hit with two new supply chain compromises csoonline | 2026-11-24 | ok |  |
| Q91 | Further: jscrambler / AsyncAPI | Wiz M-Red-Team AsyncAPI | 2026-11-24 | ok |  |
| Q92 | Further: node-ipc | node-ipc May 2026 backdoored require DNS | 2026-11-24 | ok |  |
| Q93 | Further: Shai-Hulud (Actions view) | Shai-Hulud worm shai-hulud-workflow.yml webhook.site | 2026-11-24 | ok |  |
| Q94 | Further: Shai-Hulud (Actions view) | Shai-Hulud 2.0 setup_bun.js discussion.yaml | 2026-11-24 | ok |  |
| Q95 | Further: WFX Phantom | Semgrep WFX Phantom | 2026-11-24 | ok |  |
| Q96 | Further: WFX Phantom | wfx stealer toJSON secrets exfil | 2026-11-24 | ok |  |
| Q97 | Further: ChainDrop | ChainDrop npm August 2026 | 2026-11-24 | ok |  |
| Q98 | Further: ChainDrop | Unit 42 ChainDrop Runner.Worker | 2026-11-24 | ok |  |
| Q99 | Further: ChainDrop | keyv cacheable November 15 2026 | 2026-11-24 | ok |  |
| Q100 | Further: GhostAction 2026 | GhostAction returns October 2026 | 2026-11-24 | ok |  |
| Q101 | Further: GitLab CI | GitLab CI pipeline malicious job exfiltrated CI/CD variables 2026 | 2026-11-24 | ok |  |
| Q102 | Further: pwn-request 2026 | pwn request pull_request_target exploited 2026 secrets stolen | 2026-11-24 | ok |  |
| Q103 | Further: pwn-request 2026 | prt-scan campaign | 2026-11-24 | ok |  |
| Q104 | Further: pwn-request 2026 | kubernetes-el pwn request | 2026-11-24 | ok |  |
| Q105 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | elementary-data 0.23.3 | 2026-11-24 | ok |  |
| Q106 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | durabletask | 2026-11-24 | ok |  |
| Q107 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | mrmustard 0.7.4 | 2026-11-24 | ok |  |
| Q108 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | xinference | 2026-11-24 | ok |  |
| Q109 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | durabletask rope.pyz | 2026-11-24 | ok |  |
| Q110 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | elementary.pth IMDS | 2026-11-24 | ok |  |
| Q111 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | mrmustard daemon thread | 2026-11-24 | ok |  |
| Q112 | Further: TeamPCP / Shai-Hulud lineage (PyPI) | PyPI Shai-Hulud November 2025 | 2026-11-24 | ok |  |
| Q113 | Further: Positive Technologies | deepseeek deepseekai | 2026-11-24 | ok |  |
| Q114 | Further: ReversingLabs and Socket 2025 | 2025 malicious PyPI package steals environment variables tokens Socket Zscaler campaign named | 2026-11-24 | ok |  |
| Q115 | Further: ReversingLabs and Socket 2025 | time-utils | 2026-11-24 | ok |  |
| Q116 | Further: Socket 2026 | payment SDK July 2026 | 2026-11-24 | ok |  |
| Q117 | Further: Socket 2026 | TrapDoor | 2026-11-24 | ok |  |
| Q118 | Further: LiteLLM October / late 2026 | litellm incident report October 2026 | 2026-11-24 | ok |  |
| Q119 | Further: LiteLLM October / late 2026 | compromised PyPI package credential stealer October 2026 | 2026-11-24 | ok |  |
| Q120 | Further: LiteLLM October / late 2026 | PyPI supply chain attack September 2026 | 2026-11-24 | ok |  |
| Q121 | Further: LiteLLM October / late 2026 | Microsoft agent-framework | 2026-11-24 | ok |  |
| Q122 | Further: LiteLLM October / late 2026 | pytorch lightning | 2026-11-24 | ok |  |
| Q123 | Further: LiteLLM October / late 2026 | litellm 1.107.0 cook.pth | 2026-11-24 | ok |  |
| Q124 | Further: PyPI CI check | PyPI malware checks CI environment GITHUB_ACTIONS | 2026-11-24 | ok |  |
| Q125 | Further: GitGuardian round-up (stop family 1, PyPI stream) | GitGuardian the streak continues round-up | 2026-11-24 | ok |  |
| Q126 | Further: Checkmarx/Zscaler 2025 (stop family 2, PyPI stream) | Checkmarx Zscaler malicious PyPI 2025 | 2026-11-24 | ok |  |
| Q127 | Further: Okta/Trend TeamPCP list (stop family 1, Actions stream) | Okta Trend Micro TeamPCP campaign list | 2026-11-24 | ok |  |
| Q128 | Further: StepSecurity incident list Oct/Nov 2026 (stop family 2, Actions stream) | StepSecurity Harden-Runner incident list October November 2026 | 2026-11-24 | ok |  |
| Q129 | Tools | StepSecurity Harden-Runner pricing tiers | 2026-11-24 | ok |  |
| Q130 | Tools | socket.dev pricing Free Team Business per developer month | 2026-11-24 | ok |  |
| Q131 | Tools | Aikido Security pricing Free Basic Pro Advanced per month | 2026-11-24 | ok |  |
| Q132 | Tools | Snyk plans pricing Free Team Ignite per contributing developer | 2026-11-24 | ok |  |
| Q133 | Tools | GitGuardian pricing Free Business Enterprise developers | 2026-11-24 | ok |  |
| Q134 | Tools | Endor Labs pricing page tiers | 2026-11-24 | ok |  |
| Q135 | Tools | StepSecurity pricing page Enterprise per developer Harden-Runner | 2026-11-24 | ok |  |
| Q136 | Tools | Socket GitHub app pull request dependency changes install scripts network access alerts | 2026-11-24 | ok |  |
| Q137 | Tools | Wiz pricing Wiz Code Wiz Defend runtime sensor CI/CD supply chain pricing public | 2026-11-24 | ok |  |
| Q138 | Tools | Endor Labs malware detection dependency pull request diff | 2026-11-24 | ok |  |
| Q139 | Tools | Snyk malicious package detection npm pull request checks new dependencies | 2026-11-24 | ok |  |
| Q140 | Tools | Datadog GuardDog malicious package detected npm campaign 2025 | 2026-11-24 | ok |  |
| Q141 | Tools | Phylum Veracode package firewall acquisition 2025 status | 2026-11-24 | ok |  |
| Q142 | Verify (GitHub issue search) | repo:BerriAI/litellm is:issue litellm_init.pth | 2026-11-24 | ok |  |
| Q143 | Verify (GitHub issue search) | repo:team-telnyx/telnyx-python is:issue compromised | 2026-11-24 | ok |  |
| Q144 | Verify (GitHub issue search) | repo:BerriAI/litellm is:issue 47826 | 2026-11-24 | ok |  |
| Q145 | Verify (GitHub issue search) | repo:nrwl/nx is:issue s1ngularity | 2026-11-24 | ok |  |
| Q146 | Verify (GitHub issue search) | repo:tj-actions/changed-files is:issue compromised | 2026-11-24 | ok |  |
| Q147 | Verify (GitHub issue search) | repo:microsoft/durabletask-python is:issue compromised | 2026-11-24 | ok |  |
| Q148 | Verify (GitHub issue search) | repo:elementary-data/elementary is:issue malicious | 2026-11-24 | ok |  |
| Q149 | Verify (GitHub issue search) | repo:XanaduAI/MrMustard is:issue 0.7.4 | 2026-11-24 | ok |  |
| Q150 | Verify (GitHub issue search) | repo:mistralai/client-python is:issue compromised | 2026-11-24 | ok |  |
| Q151 | Verify (GitHub issue search) | repo:TanStack/router is:issue compromised | 2026-11-24 | ok |  |
| Q152 | Verify (GitHub issue search) | repo:jaredwray/keyv is:issue malicious | 2026-11-24 | ok |  |
| Q153 | Verify (GitHub issue search) | repo:asyncapi/generator is:issue compromised | 2026-11-24 | ok |  |
| Q154 | Verify (GitHub issue search) | repo:kubernetes-el/kubernetes-el is:issue compromised | 2026-11-24 | ok |  |
| Q155 | Verify (GitHub issue search) | repo:Checkmarx/kics-github-action is:issue compromised | 2026-11-24 | ok |  |
| Q156 | Verify (GitHub issue search) | repo:PostHog/posthog-js is:issue shai-hulud | 2026-11-24 | ok |  |
| Q157 | Verify (GitHub issue search) | repo:scttcper/tinycolor is:issue compromised | 2026-11-24 | ok |  |
| Q158 | Verify (GitHub issue search) | repo:jscrambler/jscrambler is:issue compromised | 2026-11-24 | ok |  |
| Q159 | Verify (GitHub issue search) | repo:cap-js/cds-dbs is:issue malicious | 2026-11-24 | ok |  |
| Q160 | Verify (GitHub issue search) | repo:antvis/G2 is:issue compromised | 2026-11-24 | ok |  |
| Q161 | Verify (GitHub issue search) | repo:Lightning-AI/pytorch-lightning is:issue compromised | 2026-11-24 | ok |  |
| Q162 | Verify (GitHub issue search) | repo:RIAEvangelist/node-ipc is:issue 12.0.1 | 2026-11-24 | ok |  |
| Q163 | Verify (GitHub issue search) | repo:RedHatInsights/frontend-components is:issue compromised | 2026-11-24 | ok |  |
| Q164 | Verify (GitHub issue search) | repo:intercom/intercom-node is:issue 7.0.4 | 2026-11-24 | ok |  |
| Q165 | Verify (GitHub issue search) | repo:InjectiveLabs/injective-ts is:issue telemetry | 2026-11-24 | ok |  |
| Q166 | Verify (GitHub issue search) | pgserve compromised is:issue | 2026-11-24 | ok |  |
| Q167 | Verify (GitHub issue search) | react-native-international-phone-number malicious is:issue | 2026-11-24 | ok |  |
| Q168 | Verify (GitHub issue search) | repo:chalk/chalk chalk debug compromised malware is:issue | 2026-11-24 | ok |  |
| Q169 | Verify (GitHub issue search) | repo:prettier/eslint-config-prettier compromised is:issue | 2026-11-24 | ok |  |
| Q170 | Verify (GitHub issue search) | repo:axios/axios axios 1.14.1 compromised is:issue | 2026-11-24 | ok |  |
| Q171 | Verify (GitHub issue search) | trivy-action compromised 0.69.4 is:issue | 2026-11-24 | ok |  |
| Q172 | Verify (GitHub issue search) | pyphetools malicious is:issue | 2026-11-24 | ok |  |
| Q173 | Verify (GitHub issue search) | wfx-docs malicious workflow is:issue | 2026-11-24 | ok |  |
| Q174 | Verify (GitHub issue search) | openapi-react-query-codegen malicious is:issue | 2026-11-24 | ok |  |
| Q175 | Verify (GitHub issue search) | xygeni-action compromised is:issue | 2026-11-24 | ok |  |
| Q176 | Verify (GitHub issue search) | SANDWORM_MODE npm is:issue | 2026-11-24 | ok |  |
| Q177 | Verify (GitHub issue search) | repo:BerriAI/litellm litellm_init.pth (without is:issue) | 2026-11-24 | failed | HTTP 422: Query must include 'is:issue' or 'is:pull-request' (re-run with is:issue: ok) |
| Q178 | Verify (GitHub issue search) | repo:microsoft/agent-framework is:issue compromised | 2026-11-24 | failed | HTTP 422: The listed users and repositories cannot be searched |
| Q179 | Verify (GitHub issue search) | repo:asteroiddao/weavedb is:issue malicious | 2026-11-24 | failed | HTTP 422: The listed users and repositories cannot be searched |
| Q180 | Verify (GitHub issue search) | repo:namastexlabs/pgserve is:issue malicious | 2026-11-24 | failed | HTTP 422: The listed users and repositories cannot be searched |
