# Sources

Facts used in the README, the docs and `config/rules.yaml`. **None of these has been re-verified by the team yet**, so every regulatory rule that cites them carries `status: to_verify`. Check each source, then set `status: verified` and update `last_checked` in `config/rules.yaml`.

| Topic | Source | Used for | Status |
|---|---|---|---|
| SAFE violation notice (quota splitting, fines) | http://m.safe.gov.cn/safe/2024/0321/24130.html | `T4-003` | TODO: verify |
| Anti-splitting patterns (Zhong Lun) | https://www.zhonglun.com/research/articles/6642.html | `T4-003`, `Q-003` | TODO: verify |
| Quota-splitting case (Dacheng) — 34 people's quotas, USD 2.45M, RMB 830,000 fine | https://shanghai.dacheng.com/Party_2/1540.html | `T4-003`, README | TODO: verify |
| Agency 代缴学费 fraud ("real admission + fake fee payment"), Wenzhou 2025–26 | https://www.shobserver.cn/wx/detail.do?id=1147014 | `T4-001`, README, deck slide 1 | TODO: verify |
| Consulate warning (Los Angeles) — tuition-payment scams, private FX | https://losangeles.china-consulate.gov.cn/lbqw/lsbhyxz/lstx/202507/t20250704_11665031.htm | `T4-001`, `T4-004` | TODO: verify |
| MOE Safe Study Abroad advisory | https://m.163.com/dy/article/K0RCDQ0F0556BFNP.html | `T4-004` | TODO: verify |
| HSBC China education-payment documents | https://www.hsbc.com.cn/en-cn/international/products/education-payment/ | `Q-002` document checklist | TODO: verify |
| SAFE individual FX administration — USD 50,000 annual quota | Bank of China — SAFE FX compliance page (URL: TODO verify) | `Q-001` | TODO: verify |
| Personal Information Protection Law (PIPL) | Art. 6, 13–14, 47, 51 (TODO: verify article numbers) | `P-001`–`P-004` | TODO: verify |
| Measures for Labelling AI-Generated Synthetic Content, effective 1 Sep 2025 | (TODO: add official URL) | `AI-001` | TODO: verify |
| Virtual-currency speculation risk notice (2021) | (TODO: add official URL) | `T4-005` | TODO: verify |
| OWASP Top 10 for LLM Applications 2025 | https://genai.owasp.org/llm-top-10/ | security self-assessment | reference |

`docs/research/` does not exist yet. If the team adds it, it becomes the factual source and these entries should cite it.
