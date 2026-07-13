AGENT_TEMPLATES: tuple[dict, ...] = (
    {"type": "qa", "name": "知识问答", "persona": "基于企业知识库回答问题，回答需给出引用。"},
    {"type": "nl2data", "name": "智能问数", "persona": "把自然语言问题转为数据查询并解释结果。"},
    {"type": "doc_gen", "name": "文书生成", "persona": "根据上下文生成报告、邮件和通用文案。"},
    {"type": "doc_check", "name": "文书校核", "persona": "检查文档一致性、错漏和合规风险。"},
    {"type": "analysis", "name": "分析报告", "persona": "整理材料并生成结构化分析报告。"},
    {"type": "file_parse", "name": "文件解析", "persona": "解析文件并提取关键文本结构。"},
    {"type": "extract", "name": "结构化提取", "persona": "从文本和表格中提取结构化字段。"},
    {"type": "file_diff", "name": "文件比对", "persona": "对比两个文件版本并说明差异。"},
    {"type": "recommend", "name": "辅助推荐", "persona": "根据上下文推荐内容或下一步动作。"},
    {"type": "retrieve", "name": "资料检索", "persona": "面向资料库执行精准检索并返回出处。"},
    {"type": "custom", "name": "自定义智能体", "persona": "由用户自定义提示词、工具和知识库。"},
    {"type": "workflow_approval", "name": "工单审批占位", "persona": "P2 占位模板，当前不实现审批流。"},
    {"type": "form_intake", "name": "表单受理占位", "persona": "P2 占位模板，当前不实现受理流。"},
    {"type": "policy_interpret", "name": "制度解读占位", "persona": "P2 占位模板，当前不实现专属解读逻辑。"},
    {"type": "task_planner", "name": "任务规划占位", "persona": "P2 占位模板，当前不实现复杂规划。"},
    {"type": "ops_assistant", "name": "运维助手占位", "persona": "P2 占位模板，当前不实现自动巡检。"},
)


def default_config(template: dict) -> dict:
    return {
        "persona": template["persona"],
        "intent": {"enabled": False},
        "dialog_flow": {"type": "single_turn"},
        "prompt": {"style": "concise", "require_citations": template["type"] in {"qa", "retrieve"}},
        "tools": [],
        "kbs": [],
    }
