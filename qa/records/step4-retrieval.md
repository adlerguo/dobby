# Step 4 检索管道测试记录

执行时间：2026-07-14 12:40:50 +0800

KB: `84f2445a-03b4-43a5-a0db-62c99f9d1c7b`，Document: `057336b7-d9cf-43b1-9ee6-3e29f65f7e28`，chunks=7
原文已保存：`qa/env/step4-doc.txt`

## 第 1 组：match_type

| 查询 | vector | keyword | hybrid | 结论 |
|---|---|---|---|---:|
| invoice approval workflow | ['vector'] | ['keyword'] | ['vector', 'keyword'] | PASS |
| contract review | ['vector'] | ['keyword'] | ['vector', 'keyword'] | PASS |

## 第 2 组：中文关键词 R3

SQL 分词证据：`{"zh_vector": "'合同审批流程需要三级会签':1", "zh_query": "'合同审批'", "en_vector": "'approval':2 'invoice':1 'workflow':3", "en_query": "'invoice' & 'approval'"}`

| 查询 | keyword 命中 | vector 命中 | hybrid 命中 | 结论 |
|---|---:|---:|---:|---:|
| 合同审批 | 0 | 4 | 4 | FAIL/R3成立 |
| 信创云 | 0 | 4 | 4 | FAIL/R3成立 |
| 国产芯片 | 0 | 4 | 4 | FAIL/R3成立 |

## 第 3 组：引用结构

- 字段完整：True
- snippet 包含命中词：True
- doc_name 正确：True

## 第 4 组：未命中不伪造 / 阈值

| 用例 | chunks | citations | 结论 |
|---|---:|---:|---:|
| 不存在中文 keyword：红烧肉做法 | 0 | 0 | PASS |
| 不存在 hybrid + vector高阈值 | 0 | 0 | PASS |
| vector score_threshold=0.99 | 0 | 0 | PASS |
| keyword score_threshold=0.99 | 1 | 1 | PASS |

## 第 5 组：RRF 融合与去重

- top chunk channels: `['vector', 'keyword']`
- top score: `0.032018`，rank1 both 期望约 `0.032787`
- top_k=1 返回 1 条；top_k=20 返回 4 条。

## Demo 已验 / 待真 embedding key 补测

- Demo 已验：vector/keyword/hybrid 管道连通、keyword 精确命中、RRF 去重、引用结构、阈值过滤、未命中不编造。
- 待真实 embedding key 补测：向量语义质量、中文语义召回质量和排序质量。mock embedding 只能验证管道，不代表语义效果。

## 缺陷记录

- P1 `R3` Chinese keyword miss: 合同审批: `{"status": 200, "body": {"chunks": [], "citations": []}}`
- P1 `R3` Chinese keyword miss: 信创云: `{"status": 200, "body": {"chunks": [], "citations": []}}`
- P1 `R3` Chinese keyword miss: 国产芯片: `{"status": 200, "body": {"chunks": [], "citations": []}}`

## 结论

- 检索管道是否可靠：存在 P1 缺陷。
- 中文 keyword R3：成立。
- 是否可以进入 Step 5：不建议。
