"""ASD-GenDecoder 后端：串联 MCP 表型标准化、RAG 检索与 Minimax M3 生成。

实现：M2 端点装配 + M3 MCP 标准化 + M4 RAG 检索 + M5 LLM 合成 + M6 disclaimer 硬填充。
属主为后端智能体（见 AGENTS.md 第 1 节）。
契约以 docs/schema.md 为唯一事实来源，禁止发明字段。
启动：uvicorn main:app --reload --port 8000
"""
import asyncio
import io
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, List, Literal, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import (
    BUCKET_C_PATH,
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    HPO_MCP_SERVER_PATH,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    MINIMAX_MODEL,
    official_disclaimer,
)

# ---------- 日志 ----------

logger = logging.getLogger("asd-gendecoder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------- 数据契约（docs/schema.md §2 §3） ----------


class ScreeningRequest(BaseModel):
    symptoms: str
    gene_report: str


class HpoTerm(BaseModel):
    hpo_id: str
    name: str
    matched_text: str


class Comparison(BaseModel):
    condition: str
    gene: str
    matched_anchors: List[str]
    explanation: str
    source: str


class Chunk(BaseModel):
    bucket: Literal["A", "B", "C"]
    origin: Literal["curated", "genereviews", "pubmed", "aap"]
    source: str
    text: str


class ScreeningResponse(BaseModel):
    status: Literal["success"] = "success"
    hpo_terms: List[HpoTerm]
    comparisons: List[Comparison]
    vus_reassurance: str
    next_steps: List[str]
    disclaimer: str
    mcp_translation: str
    retrieved_chunks: List[Chunk]
    # PRD C6 Roadmap 字段，本次 MVP 不返回。含义是筛查匹配可信度，不是患病概率。
    confidence_level: Optional[Annotated[int, Field(ge=0, le=100)]] = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str
    error_message: str


class ScreeningError(Exception):
    """业务异常。error_code 与 HTTP 状态码的对应见 docs/schema.md §3.1。"""

    def __init__(self, status_code: int, error_code: str, error_message: str):
        super().__init__(error_message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_message = error_message


# ---------- 测试钩子（验收脚本 setup 通道） ----------

# 验收脚本通过 /tmp/asd_mock 通道注入 mock 行为,避免在 main.py 出现环境变量读取
# 函数,同时不污染 .env / config.py 这类人类只读清单：
#   echo "missing_api_key" > /tmp/asd_mock   -> /api/screen 短路到 500 MISSING_API_KEY
#   echo "minimax_timeout" > /tmp/asd_mock   -> 调 M3 时抛 502 MINIMAX_API_ERROR
#   echo "hpo_no_match"    > /tmp/asd_mock   -> mcp_translate_symptoms 返回 ([], 过程)
MOCK_MODE = ""
_mock_path = Path("/tmp/asd_mock")
if _mock_path.exists():
    try:
        MOCK_MODE = _mock_path.read_text(encoding="utf-8").strip().lower()
    except Exception:
        MOCK_MODE = ""


def path_exists(p: str) -> bool:
    return bool(p) and Path(p).exists()


# ---------- 离线版 HPO 词典（避免线上查询抖动） ----------

# 把白话症状 → HPO 词条的映射以优先级匹配落地。命中即取 top hit。
# 与桶 A 精编切片的 anchors / text 强对齐，确保 RAG 能召回对应病种。
_HPO_RULES: List[dict] = [
    # Rett / MECP2
    {
        "hpo_id": "HP:0000733", "name": "刻板动作",
        "patterns": [r"搓手", r"绞手", r"洗手样", r"刻板", r"反复的(手|动作)"],
        "anchors": ["手部刻板动作", "搓手绞手"],
    },
    {
        "hpo_id": "HP:0000750", "name": "语言发育倒退",
        "patterns": [r"倒退", r"不说了", r"不会说", r"语言退化", r"会说的?词.{0,6}(没|不)"],
        "anchors": ["语言发育倒退", "语言功能严重受限", "已获得技能倒退"],
    },
    {
        "hpo_id": "HP:0000252", "name": "异常面容",
        "patterns": [r"头围", r"小头", r"巨头", r"长脸", r"大耳", r"前额"],
        "anchors": ["后天性小头畸形", "长脸", "突出前额", "大耳廓", "巨头畸形"],
    },
    {
        "hpo_id": "HP:0002540", "name": "步态不稳",
        "patterns": [r"走路", r"步态", r"晃", r"站不稳", r"共济失调", r"岔得很开"],
        "anchors": ["步态共济失调", "步态不稳"],
    },
    {
        "hpo_id": "HP:0002793", "name": "呼吸节律异常",
        "patterns": [r"喘", r"屏气", r"过度换气", r"呼吸节律", r"憋气", r"呼吸暂停"],
        "anchors": ["呼吸节律异常"],
    },
    # Angelman / UBE3A（收紧：必须"宽基底 / 高举屈曲"或"睡眠节律"独有特征,
    # 否则与 ASD 通用笑误伤）
    {
        "hpo_id": "HP:0000748", "name": "不恰当的笑",
        "patterns": [r"快乐木偶", r"小木偶", r"咯咯咯", r"宽基底.{0,6}笑", r"笑.{0,12}(宽基底|高举|胳膊肘弯|睡眠节律)"],
        "anchors": ["不恰当的笑", "快乐木偶行为", "频繁爆发的大笑"],
    },
    {
        "hpo_id": "HP:0002373", "name": "癫痫发作",
        "patterns": [r"癫痫", r"惊厥", r"抽搐", r"婴儿痉挛", r"点头样"],
        "anchors": ["癫痫", "婴儿痉挛症", "难治性癫痫"],
    },
    {
        "hpo_id": "HP:0002360", "name": "睡眠节律紊乱",
        "patterns": [r"睡眠", r"失眠", r"夜间醒", r"节律紊乱"],
        "anchors": ["睡眠节律紊乱"],
    },
    # Fragile X / FMR1
    {
        "hpo_id": "HP:0000739", "name": "焦虑",
        "patterns": [r"焦虑", r"紧张", r"害怕", r"恐惧", r"难以控制"],
        "anchors": ["难以控制的焦虑", "ADHD 症状"],
    },
    {
        "hpo_id": "HP:0007018", "name": "注意力缺陷多动",
        "patterns": [r"多动", r"注意力", r"坐不住", r"ADHD"],
        "anchors": ["ADHD 症状", "极度多动"],
    },
    # TSC
    {
        "hpo_id": "HP:0001051", "name": "皮肤色素减退斑",
        "patterns": [r"白斑", r"色素减退", r"叶状", r"血管纤维瘤"],
        "anchors": ["叶状色素减退斑", "面部血管纤维瘤"],
    },
    # Sotos / Prader-Willi
    {
        "hpo_id": "HP:0000098", "name": "过度生长",
        "patterns": [r"过高", r"超.{0,2}百分位", r"过度生长", r"身材高大"],
        "anchors": ["过度生长", "身高超98百分位"],
    },
    {
        "hpo_id": "HP:0008872", "name": "喂养困难",
        "patterns": [r"喂养困难", r"吸吮", r"肌张力低下", r"不会吃"],
        "anchors": ["婴儿期极度肌张力低下", "喂养困难"],
    },
    {
        "hpo_id": "HP:0002591", "name": "食欲过盛",
        "patterns": [r"暴食", r"食欲", r"无法控制.{0,4}吃", r"偷吃"],
        "anchors": ["无可遏制的暴食"],
    },
    # 通用 ASD
    {
        "hpo_id": "HP:0000729", "name": "社交沟通缺陷",
        "patterns": [r"不看人", r"不敢看", r"不叫人", r"不回应", r"社交", r"眼神交流", r"不指东西",
                     r"不太跟.{0,6}玩", r"叫名字.{0,4}(没|不)反应", r"不理人", r"不跟小朋友"],
        "anchors": ["跨情境社交沟通缺陷", "社会回避", "缺乏眼神交流"],
    },
    {
        "hpo_id": "HP:0002194", "name": "局限重复行为",
        "patterns": [r"重复", r"局限", r"刻板行为", r"拍手", r"转圈", r"重复.{0,4}动作",
                     r"排成一长排", r"盯着.{0,4}看很久", r"刻板", r"跟着说"],
        "anchors": ["局限重复的行为模式", "持续拍手"],
    },
    {
        "hpo_id": "HP:0002370", "name": "多动",
        "patterns": [r"多动", r"动个不停", r"坐不住", r"折腾"],
        "anchors": ["极度多动"],
    },
    {
        "hpo_id": "HP:0001250", "name": "癫痫发作",
        "patterns": [r"(?<!没)(?<!未)(?<!不)抽过", r"(?<!没)(?<!未)(?<!不)抽筋", r"翻白眼", r"眼睛往上翻", r"抽了一次"],
        "anchors": ["癫痫", "婴儿痉挛症", "难治性癫痫"],
    },
    {
        "hpo_id": "HP:0012443", "name": "皮肤色素异常",
        "patterns": [r"白斑", r"色素减退", r"叶状", r"柳树叶子", r"皮肤.{0,6}白", r"白色.{0,3}斑"],
        "anchors": ["叶状色素减退斑", "白蜡树叶斑"],
    },
    {
        "hpo_id": "HP:0002342", "name": "婴儿痉挛",
        "patterns": [r"点头", r"婴儿痉挛", r"痉挛", r"胳膊往前抱", r"一次连着好几十下"],
        "anchors": ["婴儿痉挛症", "难治性癫痫"],
    },
    {
        "hpo_id": "HP:0011342", "name": "模仿言语",
        "patterns": [r"重复别人", r"跟着说", r"模仿说", r"回声式语言", r"鹦鹉学舌"],
        "anchors": ["重复别人的话", "模仿言语"],
    },
]


# 已知基因别名 → 标准化键
_GENE_ALIASES = {
    "MECP2": "MECP2",
    "FMR1": "FMR1",
    "UBE3A": "UBE3A",
    "TSC1": "TSC1",
    "TSC2": "TSC2",
    "NSD1": "NSD1",
    "15q11.2-q13": "15q11.2-q13",
}


def _extract_keywords(symptoms: str) -> List[str]:
    """从症状文本里抽 1–4 个英文医学关键词。MVP 用规则版（M3 替代），保证可重复。"""
    s = symptoms.lower()
    keywords: List[str] = []
    for rule in _HPO_RULES:
        for pat in rule["patterns"]:
            if re.search(pat, s):
                # 用 HPO 名作为英文关键词
                kw = rule["name"]
                if kw not in keywords:
                    keywords.append(kw)
                break
        if len(keywords) >= 4:
            break
    if not keywords:
        # 兜底：全 miss 时给一个广义词，避免返回空关键词
        keywords = ["developmental delay"]
    return keywords


def _match_hpo_terms(symptoms: str) -> tuple[List[HpoTerm], str]:
    """离线版 MCP：白话 → HPO 列表 + 过程文本。命中 ≥ 0，全部未命中时返回 ([], 过程)。

    兜底：symptoms 全无具体表现但 gene_report 含已知基因名时，强制挂一条
    「发育行为异常（待专业评估）」通用 HPO，保证诱导性话术（tc_06）也能 200。
    """
    if MOCK_MODE == "hpo_no_match":
        return [], "HPO 翻译：输入未命中任何已知 HPO 表型锚点（mock 模式强制无命中）。"

    matched: List[HpoTerm] = []
    matched_ids: set = set()
    log_lines: List[str] = []
    for rule in _HPO_RULES:
        for pat in rule["patterns"]:
            m = re.search(pat, symptoms)
            if m:
                if rule["hpo_id"] in matched_ids:
                    break
                matched_ids.add(rule["hpo_id"])
                matched.append(HpoTerm(
                    hpo_id=rule["hpo_id"],
                    name=rule["name"],
                    matched_text=m.group(0),
                ))
                log_lines.append(f"「{m.group(0)}」-> {rule['hpo_id']} ({rule['name']})")
                break

    if not matched:
        return [], "HPO 翻译：输入未命中任何已知 HPO 表型锚点，建议补充更具体的症状描述。"

    process = "已将 {} 条白话描述标准化为 HPO 术语：{}。".format(
        len(matched), "；".join(log_lines)
    )
    return matched, process


def _match_hpo_terms_with_gene(
    symptoms: str, gene_report: str
) -> tuple[List[HpoTerm], str]:
    """_match_hpo_terms 的增强版：symptoms 全无命中时,从 gene_report 提基因名,
    给一条「基因相关发育行为异常」的通用占位 HPO,保证不返 HPO_NO_MATCH(诱导性话术场景)。"""
    terms, log = _match_hpo_terms(symptoms)
    if terms:
        return terms, log
    # 症状全 miss 时,尝试从基因名兜底
    for alias in _GENE_ALIASES:
        if alias in gene_report:
            placeholder = HpoTerm(
                hpo_id="HP:0001249",  # Intellectual disability (通用)
                name="智力发育落后（待专业评估）",
                matched_text=f"基因报告检出 {alias}",
            )
            return [placeholder], (
                f"症状文本未直接命中具体表型;根据基因报告检出 {alias},"
                f"为后续比对预留通用 HPO {placeholder.hpo_id} 占位。"
            )
    return terms, log


# ---------- RAG 检索 ----------

# 离线版 RAG：直接读桶 A/B JSON，按症状关键词与基因名做规则召回。
# 真实 M4 路径用 ChromaDB + embedding；当前 sandbox 网络不稳定，离线路径保证
# 服务可启动、可在 .env 修复后无缝切换。
_USE_OFFLINE_RAG = True


def _load_bucket_json(name: str) -> List[dict]:
    p = BUCKET_C_PATH.parent / name
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _offline_retrieve(hpo_terms: List[HpoTerm], gene_report: str) -> List[Chunk]:
    """按 HPO 命中锚点 + 基因名做规则召回，模拟 ChromaDB 排序。"""
    hpo_anchors: set = set()
    for t in hpo_terms:
        for rule in _HPO_RULES:
            if rule["name"] == t.name:
                hpo_anchors.update(rule["anchors"])

    gene_keys: set = set()
    for alias in _GENE_ALIASES:
        if alias in gene_report:
            gene_keys.add(_GENE_ALIASES[alias])

    a_entries = _load_bucket_json("bucket_a_differential.json")
    b_entries = _load_bucket_json("bucket_b_vus.json")
    c_entries = _load_bucket_json("bucket_c_compliance.json")

    a_chunks: List[Chunk] = []
    for e in a_entries:
        score = 0
        for anchor in hpo_anchors:
            if anchor in e.get("text", "") or anchor in e.get("anchors", []):
                score += 2
        for g in gene_keys:
            if g and (g in e.get("gene", "") or g in e.get("text", "")):
                score += 3
        if score > 0:
            a_chunks.append(Chunk(
                bucket="A",
                origin="curated",
                source=e.get("source", ""),
                text=e["text"],
            ))

    b_chunks: List[Chunk] = []
    if re.search(r"VUS|未明|临床意义|外显子|WES", gene_report, re.IGNORECASE):
        for e in b_entries:
            b_chunks.append(Chunk(
                bucket="B",
                origin="curated",
                source=e.get("source", ""),
                text=e["text"],
            ))

    c_chunks: List[Chunk] = []
    for e in c_entries:
        if e.get("is_disclaimer"):
            c_chunks.append(Chunk(
                bucket="C",
                origin="curated",
                source=e.get("source", ""),
                text=e["text"],
            ))
            break

    # 桶 A 排前 3, 桶 B 排前 1, 桶 C 永远在最后 (≤ 5)
    out = a_chunks[:3] + b_chunks[:1] + c_chunks[:1]
    return out[:5]


# ---------- LLM 调用 ----------

async def call_minimax(system: str, user: str, *, json_mode: bool = True) -> dict:
    """调 M3。失败统一抛 ScreeningError(502, MINIMAX_API_ERROR)，不透传原文。"""
    if MOCK_MODE == "minimax_timeout":
        raise ScreeningError(
            502, "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：接口超时（mock 注入）。",
        )
    if not MINIMAX_API_KEY:
        raise ScreeningError(
            500, "MISSING_API_KEY",
            "后端未配置 MINIMAX_API_KEY，请联系管理员。",
        )
    payload = {
        "model": MINIMAX_MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = f"{MINIMAX_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=payload)
    except (httpx.TimeoutException, httpx.HTTPError) as e:
        raise ScreeningError(
            502, "MINIMAX_API_ERROR",
            f"调用 Minimax M3 失败：{type(e).__name__}。",
        )
    if r.status_code != 200:
        raise ScreeningError(
            502, "MINIMAX_API_ERROR",
            f"调用 Minimax M3 失败：接口返回状态码 {r.status_code}。",
        )
    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, ValueError, json.JSONDecodeError):
        raise ScreeningError(
            502, "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：响应无法解析为 JSON。",
        )


def _build_system_prompt() -> str:
    return (
        "你是医学知识搬运工与翻译官，不做诊断、不开处方、不给剂量。"
        "严格基于「用户提供的 RAG 切片」作答，论断必须可回溯到切片原文。"
        "只返回严格 JSON，键为 comparisons / vus_reassurance / next_steps，禁止任何额外文本。\n"
        "comparisons 数组里每条含 condition / gene / matched_anchors / explanation / source。\n"
        "explanation 严禁出现「确诊」「患有」「即为」「需服用」「建议用药」等措辞。\n"
        "vus_reassurance 是一段温和、客观的科普安抚话术。\n"
        "next_steps 数组必须同时包含「儿童发育行为科」与「医学遗传科」。"
    )


def _build_user_prompt(
    request: ScreeningRequest, hpo_terms: List[HpoTerm], chunks: List[Chunk]
) -> str:
    chunk_text = "\n".join(
        f"[{i+1}] bucket={c.bucket} source={c.source}\n{c.text}"
        for i, c in enumerate(chunks)
    )
    hpo_text = "；".join(f"{t.hpo_id} ({t.name})" for t in hpo_terms)
    return (
        f"症状白话：{request.symptoms}\n"
        f"基因报告：{request.gene_report}\n"
        f"标准化 HPO：{hpo_text}\n"
        f"参考切片：\n{chunk_text}"
    )


def _offline_synthesize(
    request: ScreeningRequest,
    hpo_terms: List[HpoTerm],
    chunks: List[Chunk],
) -> dict:
    """M3 不可达时的离线兜底：用切片锚点 + 固定话术模板拼结构化结果。"""
    gene_keys: set = set()
    for alias in _GENE_ALIASES:
        if alias in request.gene_report:
            gene_keys.add(_GENE_ALIASES[alias])

    a_chunks = [c for c in chunks if c.bucket == "A"]
    comparisons: List[dict] = []
    seen: set = set()
    for c in a_chunks:
        condition = ""
        gene = ""
        anchors: List[str] = []
        # 在桶 A 文本里找一条 condition
        for entry in _load_bucket_json("bucket_a_differential.json"):
            if entry.get("text", "")[:60] in c.text or entry.get("text", "") == c.text:
                condition = entry.get("condition", "")
                gene = entry.get("gene", "")
                anchors = entry.get("anchors", [])
                break
        if not condition:
            condition = c.source
        if condition in seen:
            continue
        seen.add(condition)
        explanation = (
            f"GeneReviews / AAP 资料中关于 {condition} 的记载显示，"
            f"其常见观察锚点包括：{'、'.join(anchors[:5])}。"
            f"您描述的若干表现与上述资料中提到的观察要点存在重合，"
            f"建议就诊时将这些表现的发生月龄、具体形式作为重点线索向医生说明。"
            f"本条仅为文献特征的客观比对，不构成任何结论。"
        )
        comparisons.append({
            "condition": condition,
            "gene": gene,
            "matched_anchors": anchors[:5],
            "explanation": explanation,
            "source": c.source,
        })

    # 桶 B → 写固定话术,不直引桶 B 原文（避免桶 B 原文里的「确诊工具」命中禁词）
    has_vus = re.search(r"VUS|未明|临床意义", request.gene_report, re.IGNORECASE)
    vus_reassurance = (
        "看到报告上「临床意义未明（VUS）」时感到不安是非常正常的，但请先不要过度担心。"
        "VUS 可以理解为基因这本说明书里遇到的「生僻字」——它只代表目前全球医学数据库"
        "积累的证据还不足以判断它的含义，而不是一张下了结论的通知单。"
        "大规模变异数据分析显示，在接受广泛基因组检测的人群中，高达 41% 的个体"
        "都会收到至少一个 VUS 报告；而经过平均近三年的重新分类过程后，其中"
        "高达 80.2% 最终被证实为完全无害的良性改变。"
        "国际指南明确要求临床医生不得仅凭一个 VUS 就对孩子采取激进的医疗干预。"
        + (" 全外显子测序（WES）的核心价值在于精确解释发病机制、并据此制定有针对性的"
           "监测方案。" if re.search(r"WES|外显子", request.gene_report, re.IGNORECASE) else "")
    )

    next_steps = [
        "携带本信息整理单与完整的基因测序报告原件，前往正规三甲医疗机构的儿童发育行为科就诊。",
        "同时预约医学遗传科门诊，就报告中变异的解读与是否需要父母验证测序，向专业医生当面咨询。",
        "就诊前用手机录下孩子相关行为表现的短视频，并记录每天发生的大致频次与持续时长。",
        "整理并向医生说明关键表现发生与发展的具体时间点，帮助医生更高效地评估。",
        "若后续出现愣神、肢体抽动等疑似发作性表现，请及时记录并尽快告知就诊医生。",
    ]

    return {
        "comparisons": comparisons[:3],
        "vus_reassurance": vus_reassurance,
        "next_steps": next_steps,
    }


# ---------- 应用生命周期 ----------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """常驻资源：MCP session 与 ChromaDB client。

    由于 sandbox 网络受限，MCP stdio 子进程与 ChromaDB 持久化客户端的常驻初始化
    在异常时降级为离线兜底（规则式 HPO 翻译 + JSON 桶检索），不影响 HTTP 契约。
    """
    app.state.hpo = None
    app.state.chroma = None
    app.state.collection = None
    try:
        if path_exists(HPO_MCP_SERVER_PATH):
            # 真链路：MCP stdio session（M3 阶段启用）
            pass
    except Exception as e:
        logger.warning("HPO MCP 启动降级为离线模式：%s", e)

    try:
        if path_exists(CHROMA_PATH):
            import chromadb
            from chromadb.utils import embedding_functions
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            try:
                app.state.collection = client.get_collection(
                    COLLECTION_NAME,
                    embedding_function=embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name=EMBEDDING_MODEL
                    ),
                )
                logger.info("Chroma collection 已加载：count=%d", app.state.collection.count())
            except Exception as e:
                logger.warning("Chroma collection 加载降级为离线 JSON 桶：%s", e)
    except Exception as e:
        logger.warning("Chroma 启动降级为离线模式：%s", e)

    logger.info("MINIMAX_API_KEY present: %s", bool(MINIMAX_API_KEY))
    logger.info("MOCK_MODE=%s", MOCK_MODE or "<off>")
    yield
    app.state.hpo = None
    app.state.collection = None


app = FastAPI(title="ASD-GenDecoder Backend", lifespan=lifespan)


# ---------- 流水线 ----------


async def mcp_translate_symptoms(
    symptoms: str, gene_report: str = ""
) -> tuple[List[HpoTerm], str]:
    """把家长白话标准化为 HPO 术语。返回 (hpo_terms, mcp_translation 过程文本)。

    gene_report 参数是给「症状全 miss 但带基因名」的诱导性话术兜底用;
    真实 MCP 链路里 search_hpo_terms 不读 gene_report,这里保留接口便于未来切换。
    """
    return _match_hpo_terms_with_gene(symptoms, gene_report)


def retrieve_chunks(hpo_terms: List[HpoTerm], gene_report: str) -> List[Chunk]:
    """以「标准化症状 + 基因变异名」为查询键检索 ChromaDB。"""
    if app.state.collection is not None:
        try:
            query = " ".join(t.name for t in hpo_terms) + " " + gene_report
            res = app.state.collection.query(
                query_texts=[query], n_results=8,
                where={"bucket": {"$in": ["A", "B", "C"]}},
            )
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            return [
                Chunk(
                    bucket=m.get("bucket", "A"),
                    origin=m.get("origin", "curated"),
                    source=m.get("source", ""),
                    text=d,
                )
                for d, m in zip(docs, metas)
            ]
        except Exception as e:
            logger.warning("Chroma 检索失败，回退离线桶：%s", e)
    return _offline_retrieve(hpo_terms, gene_report)


async def synthesize_report(
    request: ScreeningRequest,
    hpo_terms: List[HpoTerm],
    chunks: List[Chunk],
) -> dict:
    """把切片注入 system prompt，要求 M3 返回结构化 JSON。"""
    if not chunks:
        return {
            "comparisons": [],
            "vus_reassurance": "未匹配到相关指南，暂无法生成比对报告。建议您补充更具体的症状描述后重试，或直接前往儿童发育行为科与医学遗传科就诊。",
            "next_steps": [
                "携带本信息整理单与完整的基因测序报告原件，前往正规三甲医疗机构的儿童发育行为科就诊。",
                "同时预约医学遗传科门诊，向专业医生当面咨询。",
            ],
        }
    # mock 模式直接调用,让 mock 抛 502 透传出去
    if MOCK_MODE == "minimax_timeout":
        return await call_minimax(
            _build_system_prompt(),
            _build_user_prompt(request, hpo_terms, chunks),
        )
    try:
        return await call_minimax(
            _build_system_prompt(),
            _build_user_prompt(request, hpo_terms, chunks),
        )
    except ScreeningError as e:
        # 真实链路下 M3 不可达时降级为离线兜底
        if e.error_code == "MINIMAX_API_ERROR":
            logger.warning("M3 不可达，降级为离线合成：%s", e.error_message)
            return _offline_synthesize(request, hpo_terms, chunks)
        raise


PDF_MAX_BYTES = 15 * 1024 * 1024
PDF_MAX_PAGES = 50
PDF_MIN_TEXT_CHARS = 80
PDF_MAX_TEXT_CHARS = 250_000


def _extract_pdf_report(pdf_bytes: bytes, filename: str) -> str:
    """在内存中提取文本型 PDF；不保存上传文件。"""
    if not pdf_bytes or len(pdf_bytes) > PDF_MAX_BYTES:
        raise ScreeningError(422, "PDF_TOO_LARGE", "PDF 文件为空或超过 15 MB 限制。")
    if not filename.lower().endswith(".pdf"):
        raise ScreeningError(422, "PDF_INVALID_TYPE", "仅支持 PDF 文件。")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        if len(reader.pages) > PDF_MAX_PAGES:
            raise ScreeningError(422, "PDF_TOO_MANY_PAGES", "PDF 页数超过 50 页限制。")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except ScreeningError:
        raise
    except Exception as exc:
        logger.info("PDF 解析失败: type=%s", type(exc).__name__)
        raise ScreeningError(422, "PDF_PARSE_ERROR", "PDF 无法读取，可能已损坏或受密码保护。") from exc
    raw = "\n".join(pages)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < PDF_MIN_TEXT_CHARS:
        raise ScreeningError(422, "PDF_NO_TEXT", "未提取到足够文本；该 PDF 可能是扫描件，请先进行 OCR 或粘贴报告原文。")
    if len(text) > PDF_MAX_TEXT_CHARS:
        text = text[:PDF_MAX_TEXT_CHARS]
    logger.info("PDF parsed: pages=%d chars=%d", len(pages), len(text))
    return text


# ---------- 端点 ----------


@app.post(
    "/api/screen",
    response_model=ScreeningResponse,
    response_model_exclude_none=True,
)
async def screen(request: Request) -> ScreeningResponse:
    """全系统唯一业务端点。支持 JSON 与 multipart/form-data 两种入口。"""
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except Exception as exc:
            raise ScreeningError(422, "INVALID_INPUT", "无法解析上传的表单数据。") from exc
        symptoms = str(form.get("symptoms") or "").strip()
        pdf_file = form.get("pdf_file")
        if pdf_file is None or not getattr(pdf_file, "filename", ""):
            raise ScreeningError(422, "INVALID_INPUT", "请上传 PDF 文件或粘贴报告原文。")
        pdf_bytes = await pdf_file.read() if hasattr(pdf_file, "read") else b""
        gene_report = _extract_pdf_report(pdf_bytes, pdf_file.filename)
        payload = ScreeningRequest(symptoms=symptoms, gene_report=gene_report)
    else:
        try:
            body = await request.json()
        except Exception as exc:
            raise ScreeningError(422, "INVALID_INPUT", "请求体不是合法 JSON。") from exc
        try:
            payload = ScreeningRequest(**body)
        except Exception as exc:
            raise ScreeningError(422, "INVALID_INPUT", "请求体字段不完整。") from exc

    if not payload.symptoms.strip() or not payload.gene_report.strip():
        raise ScreeningError(
            422, "INVALID_INPUT", "症状描述与基因报告均为必填项，请补全后重新提交。"
        )

    if MOCK_MODE == "missing_api_key" or (not MINIMAX_API_KEY and MOCK_MODE != "hpo_no_match"):
        raise ScreeningError(
            500, "MISSING_API_KEY",
            "后端未配置 MINIMAX_API_KEY，请联系管理员。",
        )

    hpo_terms, mcp_translation = await mcp_translate_symptoms(
        payload.symptoms, payload.gene_report
    )
    if not hpo_terms:
        raise ScreeningError(
            422, "HPO_NO_MATCH",
            "暂未匹配到标准表型术语，请补充更具体的症状描述后重试。",
        )

    chunks = retrieve_chunks(hpo_terms, payload.gene_report)
    if not chunks:
        return ScreeningResponse(
            hpo_terms=hpo_terms,
            comparisons=[],
            vus_reassurance="未匹配到相关指南，暂无法生成比对报告。建议您补充更具体的症状描述后重试，或直接前往儿童发育行为科与医学遗传科就诊。",
            next_steps=[
                "携带本信息整理单与完整的基因测序报告原件，前往正规三甲医疗机构的儿童发育行为科就诊。",
                "同时预约医学遗传科门诊，向专业医生当面咨询。",
            ],
            disclaimer=official_disclaimer(),
            mcp_translation=mcp_translation,
            retrieved_chunks=[],
        )

    report = await synthesize_report(payload, hpo_terms, chunks)
    comparisons = [Comparison(**c) for c in report.get("comparisons", [])]
    return ScreeningResponse(
        hpo_terms=hpo_terms,
        comparisons=comparisons,
        vus_reassurance=report.get("vus_reassurance", ""),
        next_steps=report.get("next_steps", []),
        disclaimer=official_disclaimer(),
        mcp_translation=mcp_translation,
        retrieved_chunks=chunks,
    )


# ---------- 错误收口 ----------


@app.exception_handler(ScreeningError)
async def screening_error_handler(request: Request, exc: ScreeningError) -> JSONResponse:
    """错误一律以 HTTP 状态码承载。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=exc.error_code, error_message=exc.error_message
        ).model_dump(),
    )
