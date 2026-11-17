### large modular monorepo (home-assistant)

Run shape: 22 test jobs; full run (dev pushes, core changes). HA's own CI already runs only touched integrations on integration-only PRs, so its real average is lower.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 97% | $1.97 | $2.93 | 46 | $0.121 | $984 | $61 | $202-689 | $202-492 |
| mean skip | 82% | $1.97 | $2.93 | 83 | $0.220 | $984 | $110 | $366-689 | $366-492 |
| mean, AWS on-demand only | 82% | $1.97 | $2.93 | 83 | $0.458 | $984 | $229 | none (floor $763 > ceiling $689) | none (floor $763 > ceiling $492) |
| mean, capture overhead 1.1x | 82% | $1.97 | $2.93 | 62 | $0.165 | $984 | $83 | $276-689 | $276-492 |
| mean, customer on 8-core | 82% | $2.62 | $3.58 | 83 | $0.220 | $1,308 | $110 | $366-916 | $366-654 |
| mean, customer on 16-core | 82% | $4.05 | $5.01 | 83 | $0.220 | $2,025 | $110 | $366-1,417 | $366-1,012 |
| mean, GitHub 2025 prices | 82% | $2.62 | $3.90 | 83 | $0.220 | $1,312 | $110 | $366-918 | $366-656 |
| agents 5x (2,500 runs), mean skip | 82% | $1.97 | $2.93 | 83 | $0.220 | $4,920 | $549 | $1,831-3,444 | $1,831-2,460 |
| agents 5x, skip 51% cap | 51% | $1.97 | $2.93 | 162 | $0.428 | $4,920 | $1,070 | none (floor $3,568 > ceiling $3,444) | none (floor $3,568 > ceiling $2,460) |

### JS monorepo (docusaurus)

Run shape: 16 test jobs; the measured skip covers only the 0.3 min unit step; e2e jobs are 95% of test minutes.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 98% | $1.23 | $3.95 | 103 | $0.272 | $613 | $136 | none (floor $453 > ceiling $429) | none (floor $453 > ceiling $307) |
| mean skip | 81% | $1.23 | $3.95 | 103 | $0.272 | $613 | $136 | none (floor $454 > ceiling $429) | none (floor $454 > ceiling $307) |
| mean, AWS on-demand only | 81% | $1.23 | $3.95 | 103 | $0.567 | $613 | $284 | none (floor $946 > ceiling $429) | none (floor $946 > ceiling $307) |
| mean, capture overhead 1.1x | 81% | $1.23 | $3.95 | 103 | $0.272 | $613 | $136 | none (floor $454 > ceiling $429) | none (floor $454 > ceiling $307) |
| mean, customer on 8-core | 81% | $1.72 | $4.44 | 103 | $0.272 | $860 | $136 | $454-602 | none (floor $454 > ceiling $430) |
| mean, customer on 16-core | 81% | $2.78 | $5.50 | 103 | $0.272 | $1,388 | $136 | $454-972 | $454-694 |
| mean, GitHub 2025 prices | 81% | $1.64 | $5.57 | 103 | $0.272 | $818 | $136 | $454-572 | none (floor $454 > ceiling $409) |
| agents 5x (2,500 runs), mean skip | 81% | $1.23 | $3.95 | 103 | $0.272 | $3,066 | $681 | none (floor $2,269 > ceiling $2,146) | none (floor $2,269 > ceiling $1,533) |
| agents 5x, skip 51% cap | 51% | $1.23 | $3.95 | 103 | $0.273 | $3,066 | $683 | none (floor $2,275 > ceiling $2,146) | none (floor $2,275 > ceiling $1,533) |

### tightly coupled library (vue-core)

Run shape: 2 test jobs; PR run.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 25% | $0.09 | $0.25 | 9 | $0.023 | $46 | $12 | none (floor $39 > ceiling $32) | none (floor $39 > ceiling $23) |
| mean skip | 31% | $0.09 | $0.25 | 9 | $0.023 | $46 | $12 | none (floor $39 > ceiling $32) | none (floor $39 > ceiling $23) |
| mean, AWS on-demand only | 31% | $0.09 | $0.25 | 9 | $0.048 | $46 | $24 | none (floor $80 > ceiling $32) | none (floor $80 > ceiling $23) |
| mean, capture overhead 1.1x | 31% | $0.09 | $0.25 | 9 | $0.023 | $46 | $11 | none (floor $38 > ceiling $32) | none (floor $38 > ceiling $23) |
| mean, customer on 8-core | 31% | $0.14 | $0.30 | 9 | $0.023 | $68 | $12 | $39-48 | none (floor $39 > ceiling $34) |
| mean, customer on 16-core | 31% | $0.23 | $0.39 | 9 | $0.023 | $115 | $12 | $39-80 | $39-57 |
| mean, GitHub 2025 prices | 31% | $0.12 | $0.35 | 9 | $0.023 | $62 | $12 | $39-43 | none (floor $39 > ceiling $31) |
| agents 5x (2,500 runs), mean skip | 31% | $0.09 | $0.25 | 9 | $0.023 | $231 | $58 | none (floor $193 > ceiling $162) | none (floor $193 > ceiling $116) |
| agents 5x, skip 51% cap | 31% | $0.09 | $0.25 | 9 | $0.023 | $231 | $58 | none (floor $193 > ceiling $162) | none (floor $193 > ceiling $116) |

### Go service, small (terraform)

Run shape: 3 test jobs; PR run; the 36-job release build runs on main pushes only.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 25% | $0.23 | $0.37 | 20 | $0.053 | $115 | $26 | none (floor $88 > ceiling $81) | none (floor $88 > ceiling $58) |
| mean skip | 23% | $0.23 | $0.37 | 20 | $0.054 | $115 | $27 | none (floor $89 > ceiling $81) | none (floor $89 > ceiling $58) |
| mean, AWS on-demand only | 23% | $0.23 | $0.37 | 20 | $0.112 | $115 | $56 | none (floor $186 > ceiling $81) | none (floor $186 > ceiling $58) |
| mean, capture overhead 1.1x | 23% | $0.23 | $0.37 | 18 | $0.049 | $115 | $24 | none (floor $81 > ceiling $81) | none (floor $81 > ceiling $58) |
| mean, customer on 8-core | 23% | $0.28 | $0.43 | 20 | $0.054 | $142 | $27 | $89-99 | none (floor $89 > ceiling $71) |
| mean, customer on 16-core | 23% | $0.41 | $0.55 | 20 | $0.054 | $205 | $27 | $89-144 | $89-103 |
| mean, GitHub 2025 prices | 23% | $0.31 | $0.50 | 20 | $0.054 | $154 | $27 | $89-108 | none (floor $89 > ceiling $77) |
| agents 5x (2,500 runs), mean skip | 23% | $0.23 | $0.37 | 20 | $0.054 | $576 | $134 | none (floor $446 > ceiling $403) | none (floor $446 > ceiling $288) |
| agents 5x, skip 51% cap | 23% | $0.23 | $0.37 | 20 | $0.054 | $576 | $134 | none (floor $446 > ceiling $403) | none (floor $446 > ceiling $288) |

### Go service, large (prometheus)

Run shape: 10 test jobs; PR run.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 56% | $0.94 | $1.83 | 62 | $0.164 | $468 | $82 | $273-328 | none (floor $273 > ceiling $234) |
| mean skip | 49% | $0.94 | $1.83 | 66 | $0.174 | $468 | $87 | $289-328 | none (floor $289 > ceiling $234) |
| mean, AWS on-demand only | 49% | $0.94 | $1.83 | 66 | $0.362 | $468 | $181 | none (floor $603 > ceiling $328) | none (floor $603 > ceiling $234) |
| mean, capture overhead 1.1x | 49% | $0.94 | $1.83 | 61 | $0.163 | $468 | $81 | $271-328 | none (floor $271 > ceiling $234) |
| mean, customer on 8-core | 49% | $1.17 | $2.07 | 66 | $0.174 | $587 | $87 | $289-411 | $289-293 |
| mean, customer on 16-core | 49% | $1.72 | $2.62 | 66 | $0.174 | $862 | $87 | $289-603 | $289-431 |
| mean, GitHub 2025 prices | 49% | $1.25 | $2.51 | 66 | $0.174 | $624 | $87 | $289-437 | $289-312 |
| agents 5x (2,500 runs), mean skip | 49% | $0.94 | $1.83 | 66 | $0.174 | $2,340 | $434 | $1,447-1,638 | none (floor $1,447 > ceiling $1,170) |
| agents 5x, skip 51% cap | 49% | $0.94 | $1.83 | 66 | $0.174 | $2,340 | $434 | $1,447-1,638 | none (floor $1,447 > ceiling $1,170) |

### Django app (saleor)

Run shape: 1 test jobs; Django loads every app in every test process.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 0% | $0.22 | $0.43 | 54 | $0.143 | $108 | $71 | none (floor $238 > ceiling $76) | none (floor $238 > ceiling $54) |
| mean skip | 13% | $0.22 | $0.43 | 49 | $0.130 | $108 | $65 | none (floor $217 > ceiling $76) | none (floor $217 > ceiling $54) |
| mean, AWS on-demand only | 13% | $0.22 | $0.43 | 49 | $0.271 | $108 | $135 | none (floor $451 > ceiling $76) | none (floor $451 > ceiling $54) |
| mean, capture overhead 1.1x | 13% | $0.22 | $0.43 | 22 | $0.059 | $108 | $30 | none (floor $99 > ceiling $76) | none (floor $99 > ceiling $54) |
| mean, customer on 8-core | 13% | $0.27 | $0.48 | 49 | $0.130 | $133 | $65 | none (floor $217 > ceiling $93) | none (floor $217 > ceiling $66) |
| mean, customer on 16-core | 13% | $0.38 | $0.60 | 49 | $0.130 | $191 | $65 | none (floor $217 > ceiling $133) | none (floor $217 > ceiling $95) |
| mean, GitHub 2025 prices | 13% | $0.29 | $0.58 | 49 | $0.130 | $144 | $65 | none (floor $217 > ceiling $101) | none (floor $217 > ceiling $72) |
| agents 5x (2,500 runs), mean skip | 13% | $0.22 | $0.43 | 49 | $0.130 | $540 | $325 | none (floor $1,083 > ceiling $378) | none (floor $1,083 > ceiling $270) |
| agents 5x, skip 51% cap | 13% | $0.22 | $0.43 | 49 | $0.130 | $540 | $325 | none (floor $1,083 > ceiling $378) | none (floor $1,083 > ceiling $270) |

### small library (flask-like)

Run shape: 8 test jobs; PR run.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 0% | $0.14 | $0.34 | 14 | $0.038 | $72 | $19 | none (floor $63 > ceiling $50) | none (floor $63 > ceiling $36) |
| mean skip | 22% | $0.14 | $0.34 | 13 | $0.036 | $72 | $18 | none (floor $59 > ceiling $50) | none (floor $59 > ceiling $36) |
| mean, AWS on-demand only | 22% | $0.14 | $0.34 | 13 | $0.074 | $72 | $37 | none (floor $123 > ceiling $50) | none (floor $123 > ceiling $36) |
| mean, capture overhead 1.1x | 22% | $0.14 | $0.34 | 13 | $0.034 | $72 | $17 | none (floor $56 > ceiling $50) | none (floor $56 > ceiling $36) |
| mean, customer on 8-core | 22% | $0.24 | $0.43 | 13 | $0.036 | $121 | $18 | $59-85 | $59-60 |
| mean, customer on 16-core | 22% | $0.44 | $0.63 | 13 | $0.036 | $220 | $18 | $59-154 | $59-110 |
| mean, GitHub 2025 prices | 22% | $0.19 | $0.45 | 13 | $0.036 | $96 | $18 | $59-67 | none (floor $59 > ceiling $48) |
| agents 5x (2,500 runs), mean skip | 22% | $0.14 | $0.34 | 13 | $0.036 | $360 | $89 | none (floor $296 > ceiling $252) | none (floor $296 > ceiling $180) |
| agents 5x, skip 51% cap | 22% | $0.14 | $0.34 | 13 | $0.036 | $360 | $89 | none (floor $296 > ceiling $252) | none (floor $296 > ceiling $180) |
