# HAIKU-0 results — 30 sessions

Failed acceptance (excluded from medians): none

| task | arm | n(pass) | med fresh tok | med total tok | med cost $ | med wall s | med turns |
|---|---|---|---|---|---|---|---|
| a1 | baseline | 5 | 34703 | 530048 | 0.1056 | 138 | 17 |
| a1 | assisted | 5 | 31060 | 405331 | 0.0937 | 149 | 14 |
| a2 | baseline | 5 | 34764 | 572674 | 0.1113 | 177 | 18 |
| a2 | assisted | 5 | 30624 | 469723 | 0.0945 | 160 | 17 |
| a3 | baseline | 5 | 53340 | 1545972 | 0.2383 | 273 | 41 |
| a3 | assisted | 5 | 39643 | 811162 | 0.1461 | 200 | 28 |

## Delta per task (baseline − assisted, medians; + = assisted saves)

| task | fresh tok | total tok | cost $ | wall s | turns |
|---|---|---|---|---|---|
| a1 | +3643 (+10.5%) | +124717 (+23.5%) | +0.0119 (+11.2%) | -11 (-8.1%) | +3 (+17.6%) |
| a2 | +4140 (+11.9%) | +102951 (+18.0%) | +0.0168 (+15.1%) | +17 (+9.5%) | +1 (+5.6%) |
| a3 | +13697 (+25.7%) | +734810 (+47.5%) | +0.0922 (+38.7%) | +73 (+26.8%) | +13 (+31.7%) |

## Paired aggregate (median of per-task percentage deltas)

- fresh: +11.9%  (per task: +10.5%, +11.9%, +25.7%)
- total: +23.5%  (per task: +23.5%, +18.0%, +47.5%)
- cost: +15.1%  (per task: +11.2%, +15.1%, +38.7%)
- wall: +9.5%  (per task: -8.1%, +9.5%, +26.8%)
- turns: +17.6%  (per task: +17.6%, +5.6%, +31.7%)
