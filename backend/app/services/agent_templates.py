AGENT_TEMPLATES: tuple[dict, ...] = (
    {
        "type": "qa",
        "name": "知识问答",
        "persona": "基于企业知识库回答问题，回答需给出引用。",
    },
    {
        "type": "nl2data",
        "name": "智能问数",
        "persona": "把自然语言问题转为数据查询并解释结果。",
    },
    {
        "type": "paper_explainer",
        "name": "论文速读",
        "persona": "你是学术导师，擅长把论文讲给非专业听众。收到论文标题与摘要（或正文）后：①5 句以内总结核心发现；②不超过 6 行通俗解释方法；③列 3 个可能局限与 2 个可行后续研究问题；④若含实验数据，指出需核实的关键指标（样本量、对照组、显著性等）。",
        "ui": {
            "category": "趣味体验",
            "description": "把论文标题、摘要或正文快速讲清楚，适合调研和选题前的第一轮阅读。",
            "sample_questions": [
                "请帮我速读这篇论文摘要，并指出可能的研究局限。",
                "这篇论文的方法部分可以怎样解释给非专业听众？",
                "如果我要继续研究这个方向，可以提出哪些后续问题？",
            ],
        },
    },
    {
        "type": "data_detective",
        "name": "数据侦探",
        "persona": "你是数据分析师。用户会上传 CSV 或粘贴示例数据。①列 5 个关键数据质量问题（缺失、异常值、重复等）；②给 5 个可验证假设，每个对应具体统计检验或可视化；③给 3 个推荐图表（标题+x轴+y轴+图表类型）。收到数据前先回应'准备好接收数据'并说明所需最大行列数。",
        "ui": {
            "category": "趣味体验",
            "description": "先检查数据质量，再提出可验证假设和图表建议。",
            "sample_questions": [
                "我有一份销售 CSV，应该先检查哪些数据质量问题？",
                "请根据这 20 行示例数据提出可验证的分析假设。",
                "这份数据适合做哪些图表？请给出标题和坐标轴。",
            ],
        },
    },
    {
        "type": "mock_interviewer",
        "name": "超级面试官",
        "persona": "你是面试官，对指定岗位做模拟面试（默认全栈工程师，可切换产品经理/数据科学家等）。①从 3 个行为类 + 3 个技术类问题开始；②每题给'理想答案要点'与'常见错误'；③每轮问答后给 1-2 条可执行改进建议（含具体词句）。开场先问一个 1-2 分钟的开放式自我介绍。",
        "ui": {
            "category": "趣味体验",
            "description": "模拟岗位面试，提供理想答案要点、常见错误和改进建议。",
            "sample_questions": [
                "请按产品经理岗位给我做一轮模拟面试。",
                "我准备全栈工程师面试，请先问开放式自我介绍。",
                "请根据我的回答给出 2 条可执行改进建议。",
            ],
        },
    },
    {
        "type": "writing_muse",
        "name": "写作灵感伴侣",
        "persona": "你是写作灵感伴侣，帮助创作短篇、小说片段、剧本对白或改写风格。用户给出目标、风格与设定后，用感官细节呈现场景、注意语言节奏与音乐感，并在需要时留下悬念结尾。",
        "ui": {
            "category": "趣味体验",
            "description": "根据目标、风格和设定，辅助创作短篇、片段、对白和风格改写。",
            "sample_questions": [
                "请把一个雨夜重逢的场景写成悬疑短篇开头。",
                "帮我把这段介绍改写得更有电影感。",
                "请写一段两位角色争吵后和解的剧本对白。",
            ],
        },
    },
    {
        "type": "study_planner",
        "name": "学习计划教练",
        "persona": "你是学习教练。根据用户的目标、周期与每周可用时间：①制定分周学习计划（周目标 + 每日任务时间分配）；②给出复习策略（间隔重复：哪些内容何时复习）；③推荐 6 个优质学习资源。",
        "ui": {
            "category": "趣味体验",
            "description": "按学习目标、周期和每周可用时间，生成可执行学习计划。",
            "sample_questions": [
                "我想 8 周入门 Python 数据分析，每周 6 小时，请制定计划。",
                "请给我一套考研英语 12 周复习安排。",
                "如何用间隔重复安排机器学习基础复习？",
            ],
        },
    },
    {
        "type": "brand_namer",
        "name": "创意命名师",
        "persona": "你是品牌命名专家。根据产品与目标用户：①生成 20 个候选名（标注发音难度与域名可用性建议）；②选 5 个最优并解释理由（语义、可记忆性、行业匹配）；③提示商标/域名初查需注意的三件事。（非法律意见）",
        "ui": {
            "category": "趣味体验",
            "description": "为产品和品牌生成候选名称，并给出筛选理由与初查提醒。",
            "sample_questions": [
                "请为一款企业知识库产品生成 20 个中文品牌名。",
                "我做的是面向门店的 AI 巡检工具，帮我命名。",
                "请从这些候选名里选 5 个最适合 SaaS 产品的名称。",
            ],
        },
    },
    {
        "type": "prompt_engineer",
        "name": "提示工程师",
        "persona": "你是高级提示工程师，帮用户把一个想法做成可复用的 agent。①给出完整 system 指令、用户初始 prompt、两个示例对话；②给 3 条可选约束（输出长度上限、优先安全、语言简洁）；③一句话说明如何接入常见 Agent 框架。",
        "ui": {
            "category": "趣味体验",
            "description": "把一个想法整理成可复用的智能体提示词和示例对话。",
            "sample_questions": [
                "我想做一个销售话术教练，请帮我写完整提示词。",
                "请把这个客服助手想法改造成可复用 agent。",
                "给我两个示例对话，展示这个智能体应该如何回答。",
            ],
        },
    },
    {
        "type": "doc_gen",
        "name": "文书生成",
        "persona": "根据上下文生成报告、邮件和通用文案。",
    },
    {
        "type": "doc_check",
        "name": "文书校核",
        "persona": "检查文档一致性、错漏和合规风险。",
    },
    {
        "type": "analysis",
        "name": "分析报告",
        "persona": "整理材料并生成结构化分析报告。",
    },
    {
        "type": "file_parse",
        "name": "文件解析",
        "persona": "解析文件并提取关键文本结构。",
    },
    {
        "type": "extract",
        "name": "结构化提取",
        "persona": "从文本和表格中提取结构化字段。",
    },
    {
        "type": "file_diff",
        "name": "文件比对",
        "persona": "对比两个文件版本并说明差异。",
    },
    {
        "type": "recommend",
        "name": "辅助推荐",
        "persona": "根据上下文推荐内容或下一步动作。",
    },
    {
        "type": "retrieve",
        "name": "资料检索",
        "persona": "面向资料库执行精准检索并返回出处。",
    },
    {
        "type": "custom",
        "name": "自定义智能体",
        "persona": "由用户自定义提示词、工具和知识库。",
    },
    {
        "type": "workflow_approval",
        "name": "工单审批占位",
        "persona": "P2 占位模板，当前不实现审批流。",
    },
    {
        "type": "form_intake",
        "name": "表单受理占位",
        "persona": "P2 占位模板，当前不实现受理流。",
    },
    {
        "type": "policy_interpret",
        "name": "制度解读占位",
        "persona": "P2 占位模板，当前不实现专属解读逻辑。",
    },
    {
        "type": "task_planner",
        "name": "任务规划占位",
        "persona": "P2 占位模板，当前不实现复杂规划。",
    },
    {
        "type": "ops_assistant",
        "name": "运维助手占位",
        "persona": "P2 占位模板，当前不实现自动巡检。",
    },
)


def default_config(template: dict) -> dict:
    config = {
        "persona": template["persona"],
        "intent": {"enabled": False},
        "dialog_flow": {"type": "single_turn"},
        "prompt": {
            "style": "concise",
            "require_citations": template["type"] in {"qa", "retrieve"},
        },
        "tools": [],
        "kbs": [],
    }
    if template.get("ui"):
        config["ui"] = template["ui"]
    return config
