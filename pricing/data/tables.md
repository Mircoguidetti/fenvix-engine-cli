AWS effective rate per 4-vCPU minute: spot mix m7i.xlarge $0.00265, on-demand m7i.xlarge $0.00552, spot mix c8g.xlarge $0.00210 (ESTIMATED from DECLARED list prices). GitHub 4-core: $0.012 (DECLARED).

### Base: median skip share, spot mix, measured capture overhead, 500 runs

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 97% | 164 | $1.97 | $2.93 | 45.8 | $0.121 | $984 | $61 | $202-689 | $202-492 |
| JS monorepo (docusaurus) | 98% | 102 | $1.23 | $3.95 | 102.6 | $0.272 | $613 | $136 | none (floor $453 > ceiling $429) | none (floor $453 > ceiling $307) |
| tightly coupled library (vue-core) | 25% | 8 | $0.09 | $0.25 | 8.8 | $0.023 | $46 | $12 | none (floor $39 > ceiling $32) | none (floor $39 > ceiling $23) |
| Go service, small (terraform) | 25% | 19 | $0.23 | $0.37 | 19.9 | $0.053 | $115 | $26 | none (floor $88 > ceiling $81) | none (floor $88 > ceiling $58) |
| Go service, large (prometheus) | 56% | 78 | $0.94 | $1.83 | 61.9 | $0.164 | $468 | $82 | $273-328 | none (floor $273 > ceiling $234) |
| Django app (saleor) | 0% | 18 | $0.22 | $0.43 | 53.8 | $0.143 | $108 | $71 | none (floor $238 > ceiling $76) | none (floor $238 > ceiling $54) |
| small library (flask-like) | 0% | 12 | $0.14 | $0.34 | 14.2 | $0.038 | $72 | $19 | none (floor $63 > ceiling $50) | none (floor $63 > ceiling $36) |

### Mean skip share (the right input for a monthly bill)

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $1.97 | $2.93 | 82.9 | $0.220 | $984 | $110 | $366-689 | $366-492 |
| JS monorepo (docusaurus) | 81% | 102 | $1.23 | $3.95 | 102.8 | $0.272 | $613 | $136 | none (floor $454 > ceiling $429) | none (floor $454 > ceiling $307) |
| tightly coupled library (vue-core) | 31% | 8 | $0.09 | $0.25 | 8.7 | $0.023 | $46 | $12 | none (floor $39 > ceiling $32) | none (floor $39 > ceiling $23) |
| Go service, small (terraform) | 23% | 19 | $0.23 | $0.37 | 20.2 | $0.054 | $115 | $27 | none (floor $89 > ceiling $81) | none (floor $89 > ceiling $58) |
| Go service, large (prometheus) | 49% | 78 | $0.94 | $1.83 | 65.5 | $0.174 | $468 | $87 | $289-328 | none (floor $289 > ceiling $234) |
| Django app (saleor) | 13% | 18 | $0.22 | $0.43 | 49.0 | $0.130 | $108 | $65 | none (floor $217 > ceiling $76) | none (floor $217 > ceiling $54) |
| small library (flask-like) | 22% | 12 | $0.14 | $0.34 | 13.4 | $0.036 | $72 | $18 | none (floor $59 > ceiling $50) | none (floor $59 > ceiling $36) |

### Mean skip share, AWS on-demand only (no spot)

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $1.97 | $2.93 | 82.9 | $0.458 | $984 | $229 | none (floor $763 > ceiling $689) | none (floor $763 > ceiling $492) |
| JS monorepo (docusaurus) | 81% | 102 | $1.23 | $3.95 | 102.8 | $0.567 | $613 | $284 | none (floor $946 > ceiling $429) | none (floor $946 > ceiling $307) |
| tightly coupled library (vue-core) | 31% | 8 | $0.09 | $0.25 | 8.7 | $0.048 | $46 | $24 | none (floor $80 > ceiling $32) | none (floor $80 > ceiling $23) |
| Go service, small (terraform) | 23% | 19 | $0.23 | $0.37 | 20.2 | $0.112 | $115 | $56 | none (floor $186 > ceiling $81) | none (floor $186 > ceiling $58) |
| Go service, large (prometheus) | 49% | 78 | $0.94 | $1.83 | 65.5 | $0.362 | $468 | $181 | none (floor $603 > ceiling $328) | none (floor $603 > ceiling $234) |
| Django app (saleor) | 13% | 18 | $0.22 | $0.43 | 49.0 | $0.271 | $108 | $135 | none (floor $451 > ceiling $76) | none (floor $451 > ceiling $54) |
| small library (flask-like) | 22% | 12 | $0.14 | $0.34 | 13.4 | $0.074 | $72 | $37 | none (floor $123 > ceiling $50) | none (floor $123 > ceiling $36) |

### Mean skip share, capture overhead cut to 1.1x (engine target, not measured)

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $1.97 | $2.93 | 62.4 | $0.165 | $984 | $83 | $276-689 | $276-492 |
| JS monorepo (docusaurus) | 81% | 102 | $1.23 | $3.95 | 102.7 | $0.272 | $613 | $136 | none (floor $454 > ceiling $429) | none (floor $454 > ceiling $307) |
| tightly coupled library (vue-core) | 31% | 8 | $0.09 | $0.25 | 8.6 | $0.023 | $46 | $11 | none (floor $38 > ceiling $32) | none (floor $38 > ceiling $23) |
| Go service, small (terraform) | 23% | 19 | $0.23 | $0.37 | 18.4 | $0.049 | $115 | $24 | none (floor $81 > ceiling $81) | none (floor $81 > ceiling $58) |
| Go service, large (prometheus) | 49% | 78 | $0.94 | $1.83 | 61.4 | $0.163 | $468 | $81 | $271-328 | none (floor $271 > ceiling $234) |
| Django app (saleor) | 13% | 18 | $0.22 | $0.43 | 22.4 | $0.059 | $108 | $30 | none (floor $99 > ceiling $76) | none (floor $99 > ceiling $54) |
| small library (flask-like) | 22% | 12 | $0.14 | $0.34 | 12.7 | $0.034 | $72 | $17 | none (floor $56 > ceiling $50) | none (floor $56 > ceiling $36) |

### Mean skip share, customer on 8-core GitHub runners

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $2.62 | $3.58 | 82.9 | $0.220 | $1,308 | $110 | $366-916 | $366-654 |
| JS monorepo (docusaurus) | 81% | 102 | $1.72 | $4.44 | 102.8 | $0.272 | $860 | $136 | $454-602 | none (floor $454 > ceiling $430) |
| tightly coupled library (vue-core) | 31% | 8 | $0.14 | $0.30 | 8.7 | $0.023 | $68 | $12 | $39-48 | none (floor $39 > ceiling $34) |
| Go service, small (terraform) | 23% | 19 | $0.28 | $0.43 | 20.2 | $0.054 | $142 | $27 | $89-99 | none (floor $89 > ceiling $71) |
| Go service, large (prometheus) | 49% | 78 | $1.17 | $2.07 | 65.5 | $0.174 | $587 | $87 | $289-411 | $289-293 |
| Django app (saleor) | 13% | 18 | $0.27 | $0.48 | 49.0 | $0.130 | $133 | $65 | none (floor $217 > ceiling $93) | none (floor $217 > ceiling $66) |
| small library (flask-like) | 22% | 12 | $0.24 | $0.43 | 13.4 | $0.036 | $121 | $18 | $59-85 | $59-60 |

### Mean skip share, customer on 16-core GitHub runners

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $4.05 | $5.01 | 82.9 | $0.220 | $2,025 | $110 | $366-1,417 | $366-1,012 |
| JS monorepo (docusaurus) | 81% | 102 | $2.78 | $5.50 | 102.8 | $0.272 | $1,388 | $136 | $454-972 | $454-694 |
| tightly coupled library (vue-core) | 31% | 8 | $0.23 | $0.39 | 8.7 | $0.023 | $115 | $12 | $39-80 | $39-57 |
| Go service, small (terraform) | 23% | 19 | $0.41 | $0.55 | 20.2 | $0.054 | $205 | $27 | $89-144 | $89-103 |
| Go service, large (prometheus) | 49% | 78 | $1.72 | $2.62 | 65.5 | $0.174 | $862 | $87 | $289-603 | $289-431 |
| Django app (saleor) | 13% | 18 | $0.38 | $0.60 | 49.0 | $0.130 | $191 | $65 | none (floor $217 > ceiling $133) | none (floor $217 > ceiling $95) |
| small library (flask-like) | 22% | 12 | $0.44 | $0.63 | 13.4 | $0.036 | $220 | $18 | $59-154 | $59-110 |

### Mean skip share, GitHub 2025 list prices

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $2.62 | $3.90 | 82.9 | $0.220 | $1,312 | $110 | $366-918 | $366-656 |
| JS monorepo (docusaurus) | 81% | 102 | $1.64 | $5.57 | 102.8 | $0.272 | $818 | $136 | $454-572 | none (floor $454 > ceiling $409) |
| tightly coupled library (vue-core) | 31% | 8 | $0.12 | $0.35 | 8.7 | $0.023 | $62 | $12 | $39-43 | none (floor $39 > ceiling $31) |
| Go service, small (terraform) | 23% | 19 | $0.31 | $0.50 | 20.2 | $0.054 | $154 | $27 | $89-108 | none (floor $89 > ceiling $77) |
| Go service, large (prometheus) | 49% | 78 | $1.25 | $2.51 | 65.5 | $0.174 | $624 | $87 | $289-437 | $289-312 |
| Django app (saleor) | 13% | 18 | $0.29 | $0.58 | 49.0 | $0.130 | $144 | $65 | none (floor $217 > ceiling $101) | none (floor $217 > ceiling $72) |
| small library (flask-like) | 22% | 12 | $0.19 | $0.45 | 13.4 | $0.036 | $96 | $18 | $59-67 | none (floor $59 > ceiling $48) |

### Agents: 5x runs (2,500 / month), same per-run skip share (project mean)

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 82% | 164 | $1.97 | $2.93 | 82.9 | $0.220 | $4,920 | $549 | $1,831-3,444 | $1,831-2,460 |
| JS monorepo (docusaurus) | 81% | 102 | $1.23 | $3.95 | 102.8 | $0.272 | $3,066 | $681 | none (floor $2,269 > ceiling $2,146) | none (floor $2,269 > ceiling $1,533) |
| tightly coupled library (vue-core) | 31% | 8 | $0.09 | $0.25 | 8.7 | $0.023 | $231 | $58 | none (floor $193 > ceiling $162) | none (floor $193 > ceiling $116) |
| Go service, small (terraform) | 23% | 19 | $0.23 | $0.37 | 20.2 | $0.054 | $576 | $134 | none (floor $446 > ceiling $403) | none (floor $446 > ceiling $288) |
| Go service, large (prometheus) | 49% | 78 | $0.94 | $1.83 | 65.5 | $0.174 | $2,340 | $434 | $1,447-1,638 | none (floor $1,447 > ceiling $1,170) |
| Django app (saleor) | 13% | 18 | $0.22 | $0.43 | 49.0 | $0.130 | $540 | $325 | none (floor $1,083 > ceiling $378) | none (floor $1,083 > ceiling $270) |
| small library (flask-like) | 22% | 12 | $0.14 | $0.34 | 13.4 | $0.036 | $360 | $89 | none (floor $296 > ceiling $252) | none (floor $296 > ceiling $180) |

### Agents: 5x runs (2,500 / month), skip share = min(project mean, 51% pooled agent-push mean)

| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 51% | 164 | $1.97 | $2.93 | 161.6 | $0.428 | $4,920 | $1,070 | none (floor $3,568 > ceiling $3,444) | none (floor $3,568 > ceiling $2,460) |
| JS monorepo (docusaurus) | 51% | 102 | $1.23 | $3.95 | 103.1 | $0.273 | $3,066 | $683 | none (floor $2,275 > ceiling $2,146) | none (floor $2,275 > ceiling $1,533) |
| tightly coupled library (vue-core) | 31% | 8 | $0.09 | $0.25 | 8.7 | $0.023 | $231 | $58 | none (floor $193 > ceiling $162) | none (floor $193 > ceiling $116) |
| Go service, small (terraform) | 23% | 19 | $0.23 | $0.37 | 20.2 | $0.054 | $576 | $134 | none (floor $446 > ceiling $403) | none (floor $446 > ceiling $288) |
| Go service, large (prometheus) | 49% | 78 | $0.94 | $1.83 | 65.5 | $0.174 | $2,340 | $434 | $1,447-1,638 | none (floor $1,447 > ceiling $1,170) |
| Django app (saleor) | 13% | 18 | $0.22 | $0.43 | 49.0 | $0.130 | $540 | $325 | none (floor $1,083 > ceiling $378) | none (floor $1,083 > ceiling $270) |
| small library (flask-like) | 22% | 12 | $0.14 | $0.34 | 13.4 | $0.036 | $360 | $89 | none (floor $296 > ceiling $252) | none (floor $296 > ceiling $180) |
