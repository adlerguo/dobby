import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa"
ENV = QA / "env"
RECORDS = QA / "records"
BASE = "http://localhost:8001/api/v1"


DOC_TEXT = """invoice approval workflow requires finance owner review and final CFO approval.

contract review must check liability, confidentiality, payment terms, delivery acceptance, and dispute resolution.

The vendor onboarding policy covers security questionnaire, sanctions screening, and account provisioning.

合同审批流程需要三级会签并保留电子签章记录。

信创云平台支持国产芯片和国产操作系统适配。

发票归档规则要求按月整理纸质票据和电子票据。

Data retention for support tickets is ninety days and does not mention cooking recipes.
"""


def parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def req(method: str, path: str, *, token=None, json_body=None, raw_body=None, content_type=None, timeout=90):
    url = path if path.startswith("http") else f"{BASE}{path}"
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if raw_body is not None:
        data = raw_body
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": parse_json(text) if parse_json(text) is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "body": parse_json(text) if parse_json(text) is not None else text}


def run(cmd, *, input_text=None, timeout=120):
    p = subprocess.run(cmd, cwd=ROOT, input=input_text, text=True, capture_output=True, timeout=timeout)
    return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def compose_exec(service, args, *, input_text=None):
    return run(["docker", "compose", "exec", "-T", service, *args], input_text=input_text)


def psql(sql):
    res = compose_exec("postgres", ["psql", "-U", "app", "-d", "eap", "-A", "-F", "\t", "-q", "-c", sql])
    lines = [line for line in res["stdout"].splitlines() if line and not line.startswith("(")]
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def login_alice():
    fx = json.loads((ENV / "step1-fixtures.json").read_text())
    alice = fx["users"]["alice"]
    tenant = fx["tenants"]["A"]
    resp = req("POST", "/auth/login", json_body={"tenant_code": tenant["code"], "username": alice["username"], "password": alice["password"]})
    if resp["status"] != 200:
        raise RuntimeError(resp)
    return resp["body"]["access_token"], fx


def upload(token, kb_id, filename, content):
    boundary = f"----qa{int(time.time()*1000)}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    return req("POST", f"/kbs/{kb_id}/documents", token=token, raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")


def wait_doc(doc_id, timeout=90):
    start = time.time()
    while time.time() - start < timeout:
        rows = psql(f"select parse_status, meta::text from documents where id='{doc_id}';")
        if rows and rows[0]["parse_status"] in {"done", "failed"}:
            return rows[0]
        time.sleep(0.5)
    return {"parse_status": "timeout", "meta": "{}"}


def retrieve(token, kb_id, query, match_type="hybrid", top_k=5, score_threshold=None):
    body = {"query": query, "match_type": match_type, "top_k": top_k}
    if score_threshold is not None:
        body["score_threshold"] = score_threshold
    return req("POST", f"/kbs/{kb_id}/retrieve", token=token, json_body=body)


def contains(resp, text):
    return text in json.dumps(resp.get("body"), ensure_ascii=False)


def chunk_rows(doc_id):
    return psql(f"select id::text,seq,content,length(content) as len from chunks where doc_id='{doc_id}' order by seq;")


def tsvector_probe():
    rows = psql("select to_tsvector('simple', '合同审批流程需要三级会签')::text as zh_vector, plainto_tsquery('simple', '合同审批')::text as zh_query, to_tsvector('simple', 'invoice approval workflow')::text as en_vector, plainto_tsquery('simple', 'invoice approval')::text as en_query;")
    return rows[0] if rows else {}


def expected_rrf(candidate):
    score = 0.0
    if "vector" in candidate["match_channels"]:
        # Only one chunk is returned by vector first in this controlled top result check.
        score += 1 / 61
    if "keyword" in candidate["match_channels"]:
        score += 1 / 61
    return round(score, 6)


def main():
    token, fx = login_alice()
    ts = str(int(time.time()))
    (ENV / "step4-doc.txt").write_text(DOC_TEXT, encoding="utf-8")
    kb = req("POST", "/kbs", token=token, json_body={"name": f"QA Step4 retrieval {ts}", "type": "faq", "description": "qa-step4", "config": {"chunk_size": 180, "overlap": 20}, "embedding_model": "mock-embedding"})
    up = upload(token, kb["body"]["id"], "step4-doc.txt", DOC_TEXT)
    doc_id = up["body"]["id"]
    doc_status = wait_doc(doc_id)
    chunks = chunk_rows(doc_id)

    results = {"ts": ts, "kb": kb["body"], "document": up["body"], "doc_status": doc_status, "chunks": chunks, "groups": {}, "defects": []}

    # Group 1
    g1 = {}
    for q in ["invoice approval workflow", "contract review"]:
        g1[q] = {
            "vector": retrieve(token, kb["body"]["id"], q, "vector", 5),
            "keyword": retrieve(token, kb["body"]["id"], q, "keyword", 5),
            "hybrid": retrieve(token, kb["body"]["id"], q, "hybrid", 5),
        }
    results["groups"]["match_types"] = g1

    # Group 2
    zh_queries = ["合同审批", "信创云", "国产芯片"]
    zh = {}
    for q in zh_queries:
        zh[q] = {
            "keyword": retrieve(token, kb["body"]["id"], q, "keyword", 5),
            "vector": retrieve(token, kb["body"]["id"], q, "vector", 5),
            "hybrid": retrieve(token, kb["body"]["id"], q, "hybrid", 5),
        }
    results["groups"]["chinese_keyword"] = {"queries": zh, "tsvector": tsvector_probe()}

    # Group 3
    hit = retrieve(token, kb["body"]["id"], "invoice approval workflow", "keyword", 3)
    results["groups"]["citations"] = {
        "response": hit,
        "fields_ok": citation_fields_ok(hit),
        "snippet_contains_term": bool(hit["body"]["citations"]) and "invoice" in hit["body"]["citations"][0]["snippet"].lower(),
        "doc_name_ok": bool(hit["body"]["citations"]) and hit["body"]["citations"][0]["doc_name"] == "step4-doc.txt",
    }

    # Group 4
    miss_keyword = retrieve(token, kb["body"]["id"], "红烧肉做法", "keyword", 5)
    miss_hybrid_high = retrieve(token, kb["body"]["id"], "红烧肉做法", "hybrid", 5, score_threshold=0.99)
    vector_high = retrieve(token, kb["body"]["id"], "invoice approval workflow", "vector", 5, score_threshold=0.99)
    keyword_high = retrieve(token, kb["body"]["id"], "invoice approval workflow", "keyword", 5, score_threshold=0.99)
    results["groups"]["no_fabrication"] = {
        "missing_keyword": miss_keyword,
        "missing_hybrid_high_threshold": miss_hybrid_high,
        "vector_high_threshold": vector_high,
        "keyword_high_threshold": keyword_high,
    }

    # Group 5
    dedupe = retrieve(token, kb["body"]["id"], "invoice approval workflow", "hybrid", 5)
    top1 = retrieve(token, kb["body"]["id"], "invoice approval workflow", "hybrid", 1)
    top20 = retrieve(token, kb["body"]["id"], "invoice approval workflow", "hybrid", 20)
    results["groups"]["rrf_dedupe"] = {
        "dedupe": dedupe,
        "top1": top1,
        "top20": top20,
        "expected_top_score_if_rank1_both": 0.032787,
    }

    assess(results)
    (ENV / "step4-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render(results)
    (RECORDS / "step4-retrieval.md").write_text(md, encoding="utf-8")
    print(md)


def citation_fields_ok(resp):
    required = {"chunk_id", "doc_id", "doc_name", "seq", "content_length", "score", "vector_score", "text_score", "match_channels", "snippet"}
    cites = resp["body"].get("citations", []) if resp["status"] == 200 else []
    return bool(cites) and all(required.issubset(c.keys()) for c in cites)


def assess(results):
    g1 = results["groups"]["match_types"]
    for q, modes in g1.items():
        if not modes["vector"]["body"]["chunks"] or "vector" not in modes["vector"]["body"]["chunks"][0]["match_channels"]:
            results["defects"].append({"severity": "P1", "group": "match_types", "name": f"vector channel missing {q}", "evidence": modes["vector"]})
        if not contains(modes["keyword"], q) or "keyword" not in json.dumps(modes["keyword"]["body"], ensure_ascii=False):
            results["defects"].append({"severity": "P1", "group": "match_types", "name": f"keyword miss {q}", "evidence": modes["keyword"]})
    zh = results["groups"]["chinese_keyword"]["queries"]
    for q, modes in zh.items():
        if not contains(modes["keyword"], q):
            results["defects"].append({"severity": "P1", "group": "R3", "name": f"Chinese keyword miss: {q}", "evidence": modes["keyword"]})
    cit = results["groups"]["citations"]
    if not (cit["fields_ok"] and cit["snippet_contains_term"] and cit["doc_name_ok"]):
        results["defects"].append({"severity": "P1", "group": "citations", "name": "citation fields/snippet invalid", "evidence": cit})
    nf = results["groups"]["no_fabrication"]
    if nf["missing_keyword"]["body"]["chunks"] or nf["missing_keyword"]["body"]["citations"]:
        results["defects"].append({"severity": "P1", "group": "no_fabrication", "name": "keyword missing query returned citations", "evidence": nf["missing_keyword"]})
    if nf["vector_high_threshold"]["body"]["chunks"]:
        results["defects"].append({"severity": "P2", "group": "threshold", "name": "vector high threshold did not filter", "evidence": nf["vector_high_threshold"]})
    rrf = results["groups"]["rrf_dedupe"]["dedupe"]
    chunks = rrf["body"]["chunks"]
    if chunks:
        ids = [c["id"] for c in chunks]
        if len(ids) != len(set(ids)):
            results["defects"].append({"severity": "P1", "group": "rrf", "name": "duplicate chunk returned", "evidence": rrf})
        both = [c for c in chunks if set(c["match_channels"]) == {"vector", "keyword"}]
        if not both:
            results["defects"].append({"severity": "P1", "group": "rrf", "name": "no merged vector+keyword chunk", "evidence": rrf})


def short(obj, max_len=220):
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def render(results):
    lines = ["# Step 4 检索管道测试记录", "", f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S %z')}", "", f"KB: `{results['kb']['id']}`，Document: `{results['document']['id']}`，chunks={len(results['chunks'])}", "原文已保存：`qa/env/step4-doc.txt`", ""]
    lines += ["## 第 1 组：match_type", "", "| 查询 | vector | keyword | hybrid | 结论 |", "|---|---|---|---|---:|"]
    for q, modes in results["groups"]["match_types"].items():
        v = modes["vector"]["body"]["chunks"][0]["match_channels"] if modes["vector"]["body"]["chunks"] else []
        k = modes["keyword"]["body"]["chunks"][0]["match_channels"] if modes["keyword"]["body"]["chunks"] else []
        h = modes["hybrid"]["body"]["chunks"][0]["match_channels"] if modes["hybrid"]["body"]["chunks"] else []
        ok = bool(v) and bool(k) and bool(h)
        lines.append(f"| {q} | {v} | {k} | {h} | {'PASS' if ok else 'FAIL'} |")
    lines += ["", "## 第 2 组：中文关键词 R3", "", f"SQL 分词证据：`{short(results['groups']['chinese_keyword']['tsvector'])}`", "", "| 查询 | keyword 命中 | vector 命中 | hybrid 命中 | 结论 |", "|---|---:|---:|---:|---:|"]
    for q, modes in results["groups"]["chinese_keyword"]["queries"].items():
        k = len(modes["keyword"]["body"]["chunks"])
        v = len(modes["vector"]["body"]["chunks"])
        h = len(modes["hybrid"]["body"]["chunks"])
        hit = contains(modes["keyword"], q)
        lines.append(f"| {q} | {k} | {v} | {h} | {'PASS/R3不成立' if hit else 'FAIL/R3成立'} |")
    lines += ["", "## 第 3 组：引用结构", "", f"- 字段完整：{results['groups']['citations']['fields_ok']}", f"- snippet 包含命中词：{results['groups']['citations']['snippet_contains_term']}", f"- doc_name 正确：{results['groups']['citations']['doc_name_ok']}", ""]
    nf = results["groups"]["no_fabrication"]
    lines += ["## 第 4 组：未命中不伪造 / 阈值", "", "| 用例 | chunks | citations | 结论 |", "|---|---:|---:|---:|", f"| 不存在中文 keyword：红烧肉做法 | {len(nf['missing_keyword']['body']['chunks'])} | {len(nf['missing_keyword']['body']['citations'])} | {'PASS' if not nf['missing_keyword']['body']['chunks'] else 'FAIL'} |", f"| 不存在 hybrid + vector高阈值 | {len(nf['missing_hybrid_high_threshold']['body']['chunks'])} | {len(nf['missing_hybrid_high_threshold']['body']['citations'])} | {'PASS' if not nf['missing_hybrid_high_threshold']['body']['chunks'] else 'OBSERVE'} |", f"| vector score_threshold=0.99 | {len(nf['vector_high_threshold']['body']['chunks'])} | {len(nf['vector_high_threshold']['body']['citations'])} | {'PASS' if not nf['vector_high_threshold']['body']['chunks'] else 'FAIL'} |", f"| keyword score_threshold=0.99 | {len(nf['keyword_high_threshold']['body']['chunks'])} | {len(nf['keyword_high_threshold']['body']['citations'])} | {'PASS' if nf['keyword_high_threshold']['body']['chunks'] else 'FAIL'} |", ""]
    rrf = results["groups"]["rrf_dedupe"]
    top = rrf["dedupe"]["body"]["chunks"][0] if rrf["dedupe"]["body"]["chunks"] else {}
    lines += ["## 第 5 组：RRF 融合与去重", "", f"- top chunk channels: `{top.get('match_channels')}`", f"- top score: `{top.get('score')}`，rank1 both 期望约 `{rrf['expected_top_score_if_rank1_both']}`", f"- top_k=1 返回 {len(rrf['top1']['body']['chunks'])} 条；top_k=20 返回 {len(rrf['top20']['body']['chunks'])} 条。", ""]
    lines += ["## Demo 已验 / 待真 embedding key 补测", "", "- Demo 已验：vector/keyword/hybrid 管道连通、keyword 精确命中、RRF 去重、引用结构、阈值过滤、未命中不编造。", "- 待真实 embedding key 补测：向量语义质量、中文语义召回质量和排序质量。mock embedding 只能验证管道，不代表语义效果。", ""]
    lines += ["## 缺陷记录", ""]
    if results["defects"]:
        for d in results["defects"]:
            lines.append(f"- {d['severity']} `{d['group']}` {d['name']}: `{short(d['evidence'])}`")
    else:
        lines.append("- 未发现阻断性缺陷；R3 在当前精确短语查询下未复现。")
    lines += ["", "## 结论", ""]
    has_p1 = any(d["severity"] == "P1" for d in results["defects"])
    r3 = [d for d in results["defects"] if d["group"] == "R3"]
    lines.append(f"- 检索管道是否可靠：{'是，demo 管道通过' if not has_p1 else '存在 P1 缺陷'}。")
    lines.append(f"- 中文 keyword R3：{'成立' if r3 else '本轮未复现；simple 分词证据仍显示中文整段成 token，有隐患'}。")
    lines.append(f"- 是否可以进入 Step 5：{'可以' if not has_p1 else '不建议'}。")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
