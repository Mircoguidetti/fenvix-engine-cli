## Desk survey (§6)

Date checked: 2026-11-25

| product | what is sold | public price | official URL | status (VERIFIED quote / UNVERIFIED) |
|---|---|---|---|---|
| mutant (Ruby, mbj/mutant) | Commercial subscription to run mutant on commercial code, per developer (identified by git author email), any number of private repos | 30$ / 1 month; 250$ / 1 year (also 30€ / 250€); "per developer using mutant on any number of repositories" | https://github.com/mbj/mutant/blob/main/docs/commercial.md | VERIFIED: "Costs are **per developer using mutant on any number of repositories**." Table rows: "USD \| 1 month \| 30$" and "USD \| 1 year \| 250$". (A search summary of older docs cited $300/year; the current page says 250$.) |
| Arcmutate | Commercial extensions/plugins for PIT (pitest), Java/Kotlin mutation testing | none published (could not check) | https://www.arcmutate.com/ | UNVERIFIED: host does not resolve from this sandbox (network allowlist); web search returned no pricing page. |
| Stryker Dashboard | Hosted storage and display of Stryker mutation reports, plus a mutation-score badge | none published (no paid tier found) | https://dashboard.stryker-mutator.io/ (source: https://github.com/stryker-mutator/stryker-dashboard) | UNVERIFIED for price: dashboard site blocked from sandbox. GitHub repo page opened: "the place to host your mutation testing reports online"; Apache-2.0; it mentions no pricing. |
| Mutahunter (codeintegrity-ai) | Open-source LLM-based mutation testing tool; you pay the LLM provider for tokens. No hosted or paid tier found | none published (AGPL-3.0; LLM API cost per run) | https://github.com/codeintegrity-ai/mutahunter | VERIFIED (no-price offer): "Open Source, Language Agnostic Mutation Testing"; README sample shows "Total Cost: $0.00060 USD" (LLM spend). |
| Mutator (mutator.app) | Web-based (hosted) mutation testing and code-transformation tool | none published (GetApp lists free trial / free version) | https://mutator.app/ | UNVERIFIED: host blocked from sandbox. Only third-party listings (GetApp/Capterra) seen, with no price. |
| Diffblue Cover | AI unit-test generation for Java. Not confirmed to sell mutation testing | n/a (not checked) | https://www.diffblue.com/pricing | UNVERIFIED: host blocked from sandbox. Mutation testing was not confirmed as a product feature, so it is listed only as an excluded candidate. |

Excluded: Meta ACH (mutation-guided LLM test generation, arXiv 2501.12862) and Sapienz are internal research systems, not products for sale. No Codecov/Sentry mutation-testing offer was found.

Limits: this sandbox's network allowlist blocked most vendor domains (arcmutate.com, dashboard.stryker-mutator.io, mutator.app, diffblue.com), so only pages on GitHub could be opened. Rows marked UNVERIFIED rely on search snippets or nothing and should be re-checked from an unrestricted network. No vendor was contacted. None of the products found sells "faster mutation runs" as a separately priced service.
