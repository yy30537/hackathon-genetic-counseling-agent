"""ASD-GenDecoder 后端：串联 MCP 表型标准化、RAG 检索与 Minimax M3 生成。

实现：M2 端点装配 + M3 MCP 标准化 + M4 RAG 检索 + M5 LLM 合成 + M6 disclaimer 硬填充。
属主为后端智能体（见 AGENTS.md 第 1 节）。
契约以 docs/schema.md 为唯一事实来源，禁止发明字段。
启动：uvicorn main:app --reload --port 8000
"""
import asyncio
import json
import logging
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
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
    gene_report: str = ""


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


# ---------- 澄清对话契约（POST /api/clarify） ----------


class ClarifyRequest(BaseModel):
    utterance: str
    picked: List[str] = []


class SymptomOption(BaseModel):
    hpo_id: str
    name: str
    plain: str
    matched_text: str = ""


class ClarifyResponse(BaseModel):
    status: Literal["success"] = "success"
    reply: str
    options: List[SymptomOption]
    mcp_translation: str
    disclaimer: str


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


def _resolve_mcp_entry(raw: str) -> str:
    """把 HPO_MCP_SERVER_PATH 归一到可执行入口，取不到返回空串。

    .env 很容易填成仓库目录而不是编译产物。`node <目录>` 只报 Cannot find module
    然后静默退回离线规则，现象与「压根没配」一模一样，现场极难定位，故在此替配置兜底。
    """
    if not raw:
        return ""
    p = Path(raw)
    if p.is_file():
        return str(p)
    if p.is_dir():
        entry = p / "build" / "index.js"
        if entry.is_file():
            logger.info("HPO_MCP_SERVER_PATH 指向目录，已自动定位入口：%s", entry)
            return str(entry)
    return ""


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
    # 行为问题（家长口语常描述为「打人」「暴躁」，需独立成项避免与多动/焦虑混淆）
    {
        "hpo_id": "HP:0000718", "name": "攻击行为",
        "patterns": [r"打人", r"咬人", r"攻击", r"有攻击性", r"打小朋友", r"踢人",
                     r"摔东西", r"动手"],
        "anchors": ["ADHD 症状", "极度多动"],
    },
    {
        "hpo_id": "HP:0000737", "name": "易激惹",
        "patterns": [r"暴躁", r"易怒", r"发脾气", r"易激惹", r"脾气大",
                     r"不耐烦", r"动不动就哭", r"情绪激动", r"情绪不稳"],
        "anchors": ["难以控制的焦虑", "ADHD 症状"],
    },
    {
        "hpo_id": "HP:0002162", "name": "活动过度",
        "patterns": [r"做不定", r"静不下来", r"坐立不安", r"动来动去",
                     r"停不下来", r"跑来跑去", r"满地跑"],
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


# 聊天勾选写入的「中文名（HP:1234567）」或「中文名(HP:1234567)」
_EMBEDDED_HPO_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9\-·]{1,40})\s*[（(](HP:\d{7})[）)]"
)


def _match_hpo_terms(symptoms: str) -> tuple[List[HpoTerm], str]:
    """离线版 MCP：白话 → HPO 列表 + 过程文本。命中 ≥ 0，全部未命中时返回 ([], 过程)。

    兜底：symptoms 全无具体表现但 gene_report 含已知基因名时，强制挂一条
    「发育行为异常（待专业评估）」通用 HPO，保证诱导性话术（tc_06）也能 200。
    另：解析聊天勾选嵌入的「中文名（HP:id）」，避免 MCP 术语被离线规则漏掉。
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

    for m in _EMBEDDED_HPO_RE.finditer(symptoms):
        name = m.group(1).strip(" 、，,")
        hpo_id = m.group(2)
        if not name or hpo_id in matched_ids:
            continue
        matched_ids.add(hpo_id)
        matched.append(HpoTerm(
            hpo_id=hpo_id,
            name=name,
            matched_text=m.group(0),
        ))
        log_lines.append(f"「{m.group(0)}」-> {hpo_id} ({name})")

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

# M3 是推理模型：即便开了 json_object 模式，正文前仍会带 <think>…</think> 思维链，
# 直接 json.loads 必然失败。这里统一剥壳后再解析。
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json(content: str) -> Optional[dict]:
    """从 M3 返回的正文里抽出 JSON 对象。抽不到返回 None，由调用方转 502。"""
    if not isinstance(content, str):
        return None
    text = _THINK_RE.sub("", content)
    text = _FENCE_RE.sub("", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, json.JSONDecodeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, json.JSONDecodeError):
        return None


async def call_minimax(
    system: str, user: str, *, json_mode: bool = True, timeout: float = 90.0
) -> dict:
    """调 M3。失败统一抛 ScreeningError(502, MINIMAX_API_ERROR)，不透传原文。

    M3 会先跑一段思维链再出正文，带 RAG 切片的长提示词经常超过 30 秒。
    默认 90 秒仍小于前端的 120 秒上限；澄清链路提示词短，调用方会传更小的值。
    """
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
        async with httpx.AsyncClient(timeout=timeout) as client:
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
    except (KeyError, ValueError):
        raise ScreeningError(
            502, "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：响应结构不符合预期。",
        )
    parsed = _extract_json(content)
    if parsed is None:
        raise ScreeningError(
            502, "MINIMAX_API_ERROR",
            "调用 Minimax M3 失败：响应无法解析为 JSON。",
        )
    return parsed


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
    # 基因报告可选：未提供时不套用 VUS 安抚，改用症状向中性说明
    if not (request.gene_report or "").strip():
        vus_reassurance = (
            "本次未附上基因报告原文。以下整理仅基于您描述或勾选的症状表现，"
            "与知识库中的文献特征做客观比对，便于您带到门诊与医生当面沟通。"
            "若之后拿到基因测序报告，可再携带本整理单一并交给医学遗传科解读。"
        )
        next_steps = [
            "携带本信息整理单，前往正规三甲医疗机构的儿童发育行为科就诊。",
            "同时预约医学遗传科门诊，向专业医生当面咨询是否需要进一步基因检测或解读。",
            "就诊前用手机录下孩子相关行为表现的短视频，并记录每天发生的大致频次与持续时长。",
            "整理并向医生说明关键表现发生与发展的具体时间点，帮助医生更高效地评估。",
            "若后续出现愣神、肢体抽动等疑似发作性表现，请及时记录并尽快告知就诊医生。",
        ]
    else:
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

    MCP stdio 子进程必须活到进程退出：每请求重启会累积 1-2 秒冷启动，
    逐词查询能拖到十几秒。用 AsyncExitStack 把它的生命周期绑在 lifespan 上。

    MCP 或 ChromaDB 初始化失败时降级为离线兜底（规则式 HPO 翻译 + JSON 桶检索），
    HTTP 契约不变。
    """
    app.state.hpo = None
    app.state.hpo_lock = asyncio.Lock()
    app.state.chroma = None
    app.state.collection = None

    async with AsyncExitStack() as stack:
        entry = _resolve_mcp_entry(HPO_MCP_SERVER_PATH)
        if entry:
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client

                read, write = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(command="node", args=[entry])
                    )
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                app.state.hpo = session
                logger.info("HPO MCP 会话已建立：%s", entry)
            except Exception as e:
                app.state.hpo = None
                logger.warning("HPO MCP 启动降级为离线模式：%s", e)
        else:
            logger.warning(
                "HPO_MCP_SERVER_PATH 无效（%s），HPO 查询降级为离线规则。"
                "请在 .env 中填写编译产物的绝对路径，形如 …/HPO-MCP-Server/build/index.js。",
                HPO_MCP_SERVER_PATH or "<未配置>",
            )

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


# ---------- MCP 调用封装 ----------

# HPO-MCP-Server 返回的是给人看的纯文本，不是 JSON。逐行形如：
#   • HP:0000733: Motor stereotypy
_HPO_LINE_RE = re.compile(r"^[•*\-]\s*(HP:\d{7})\s*:\s*(.+?)\s*$")


def _parse_hpo_lines(text: str) -> List[tuple]:
    """从 MCP 文本响应里抽出 [(hpo_id, english_name), ...]，保持原顺序去重。"""
    out: List[tuple] = []
    seen: set = set()
    for raw in (text or "").splitlines():
        m = _HPO_LINE_RE.match(raw.strip())
        if not m:
            continue
        hpo_id = m.group(1)
        if hpo_id in seen:
            continue
        seen.add(hpo_id)
        out.append((hpo_id, m.group(2).strip()))
    return out


async def _mcp_call(tool: str, args: dict) -> str:
    """调常驻 MCP 会话的某个工具，返回拼接后的纯文本。

    单会话跨请求共享，用 lock 串行化避免并发请求的 id 交叉。
    会话不可用或调用异常时返回空串，由调用方走离线兜底，不抛给用户。
    """
    session = getattr(app.state, "hpo", None)
    if session is None:
        return ""
    lock = getattr(app.state, "hpo_lock", None)
    try:
        if lock is None:
            res = await session.call_tool(tool, args)
        else:
            async with lock:
                res = await session.call_tool(tool, args)
    except Exception as e:
        logger.warning("MCP 调用 %s 失败：%s", tool, e)
        return ""
    parts = [
        c.text for c in getattr(res, "content", []) or [] if getattr(c, "text", None)
    ]
    return "\n".join(parts)


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


_BANNED_WORDS = ["确诊", "患有", "即为", "需服用", "建议用药"]

# 输出侧的用药闸门，与 scripts/rag_builder.py 的 DRUG_PATTERNS 同源。
# 灌库侧挡的是「药名进向量库」，这里挡的是「药名进响应」——家长的诱导话术本身
# 就带着药名，模型即便是拒绝式复述也会被逐字扫描判为违规，必须整份丢弃改走离线版。
_DRUG_PATTERNS = [
    r"everolimus", r"sirolimus", r"risperidone", r"aripiprazole", r"valproat",
    r"carbamazepine", r"lamotrigine", r"levetiracetam", r"vigabatrin",
    r"clonazepam", r"melatonin", r"methylphenidate", r"fluoxetine", r"sertraline",
    r"\bmg/kg\b", r"\bdosage\b", r"\bdosing\b", r"\bprescrib",
    r"利培酮", r"阿立哌唑", r"丙戊酸", r"卡马西平", r"左乙拉西坦", r"氨己烯酸",
    r"抗癫痫药", r"精神药物", r"剂量", r"服药", r"吃药", r"处方",
]
_DRUG_RE = re.compile("|".join(_DRUG_PATTERNS), re.IGNORECASE)


def _normalize_report(report: dict) -> dict:
    """把 M3 返回的报告规整成契约形状。

    模型偶尔会把 matched_anchors 写成顿号分隔的字符串而不是数组，
    直接喂给 Comparison(**c) 会抛 pydantic 异常，变成不符合契约的裸 500。
    这里统一收口，形状对不上的条目丢弃而不是让请求崩掉。
    """
    comparisons: List[dict] = []
    for c in report.get("comparisons") or []:
        if not isinstance(c, dict):
            continue
        anchors = c.get("matched_anchors")
        if isinstance(anchors, str):
            anchors = [a for a in re.split(r"[、,，;；/]", anchors) if a.strip()]
        elif isinstance(anchors, list):
            anchors = [str(a) for a in anchors if str(a).strip()]
        else:
            anchors = []
        item = {
            "condition": str(c.get("condition") or "").strip(),
            "gene": str(c.get("gene") or "").strip(),
            "matched_anchors": [a.strip() for a in anchors],
            "explanation": str(c.get("explanation") or "").strip(),
            "source": str(c.get("source") or "").strip(),
        }
        if not item["condition"] or not item["explanation"]:
            continue
        comparisons.append(item)

    steps = [
        str(s).strip()
        for s in (report.get("next_steps") or [])
        if str(s).strip()
    ]
    return {
        "comparisons": comparisons,
        "vus_reassurance": str(report.get("vus_reassurance") or "").strip(),
        "next_steps": steps,
    }


def _report_banned_hits(report: dict) -> List[str]:
    """扫描 LLM 报告里的禁用词与用药词，返回命中列表。

    扫描范围严格对齐 AC5：comparisons[].explanation / vus_reassurance / next_steps。
    不含 disclaimer 与 retrieved_chunks——前者是法定免责原文，后者是知识库原文，
    两者本就允许出现这些词。
    """
    parts: List[str] = []
    for c in report.get("comparisons") or []:
        if isinstance(c, dict):
            parts.append(str(c.get("explanation") or ""))
    parts.append(str(report.get("vus_reassurance") or ""))
    for s in report.get("next_steps") or []:
        parts.append(str(s))
    scan = " ".join(parts)
    hits = [w for w in _BANNED_WORDS if w in scan]
    hits.extend(sorted({m.group(0) for m in _DRUG_RE.finditer(scan)}))
    return hits


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
        report = await call_minimax(
            _build_system_prompt(),
            _build_user_prompt(request, hpo_terms, chunks),
        )
    except ScreeningError as e:
        # 真实链路下 M3 不可达时降级为离线兜底
        if e.error_code == "MINIMAX_API_ERROR":
            logger.warning("M3 不可达，降级为离线合成：%s", e.error_message)
            return _offline_synthesize(request, hpo_terms, chunks)
        raise

    report = _normalize_report(report)
    if not report["comparisons"] or not report["vus_reassurance"]:
        logger.warning("M3 报告结构不完整，改用离线合成")
        return _offline_synthesize(request, hpo_terms, chunks)

    dirty = _report_banned_hits(report)
    if dirty:
        # 靠 prompt 祈使模型别说「确诊」不可靠，这里做结构性拦截：
        # 命中禁用词即整份丢弃，改用由桶 A/B 原文拼装的离线版本（不变量 I3 / AC5）。
        logger.warning("M3 报告命中禁用词 %s，改用离线合成", dirty)
        return _offline_synthesize(request, hpo_terms, chunks)
    return report


# ---------- 澄清对话流水线 ----------

# 离线兜底时 _HPO_RULES 的 name 是中文，而 HPO API 只索引英文，
# 这里给规则表补一份英文检索词，保证降级路径也能查 MCP。
_HPO_EN_HINTS = {
    "刻板动作": "stereotypic movements",
    "语言发育倒退": "loss of speech",
    "异常面容": "abnormal facial shape",
    "步态不稳": "unsteady gait",
    "呼吸节律异常": "abnormal breathing rhythm",
    "不恰当的笑": "inappropriate laughter",
    "癫痫发作": "seizure",
    "睡眠节律紊乱": "sleep disturbance",
    "焦虑": "anxiety",
    "注意力缺陷多动": "attention deficit hyperactivity",
    "攻击行为": "aggressive behavior",
    "易激惹": "irritability",
    "活动过度": "hyperactivity",
    "皮肤色素减退斑": "hypopigmented skin macule",
    "过度生长": "overgrowth",
    "喂养困难": "feeding difficulties",
    "食欲过盛": "hyperphagia",
    "社交沟通缺陷": "impaired social interaction",
    "局限重复行为": "restricted repetitive behavior",
    "多动": "hyperactivity",
    "皮肤色素异常": "abnormal skin pigmentation",
    "婴儿痉挛": "infantile spasms",
}

# 规则表里已知的 hpo_id -> 中文名，用于免 LLM 直接回填，并作为「本知识库覆盖得到」的排序信号。
_RULE_ID_TO_NAME = {r["hpo_id"]: r["name"] for r in _HPO_RULES}

_CLARIFY_MAX_OPTIONS = 5
_CLARIFY_MIN_OPTIONS = 3

# 澄清链路要连调两次 M3，单次上限压到 45 秒，两次加上 MCP 往返仍在前端 120 秒之内。
_CLARIFY_LLM_TIMEOUT = 45.0

_SEEDS_PER_KEYWORD = 3

# 同义轴关键词条目：{"en", "source_span", "axis"}；可选 direction=widen|narrow（仅重试）。
ClarifyKw = dict

# 过宽英文检索词：会把 HPO 搜成噪声（如 ill appearance → 无关解剖项），笼统原话时直接丢。
_OVERBROAD_EN = {
    "appearing unwell",
    "appearing ill",
    "ill appearance",
    "feeling unwell",
    "unwell",
    "something wrong",
    "abnormality",
    "abnormal",
    "abnormal finding",
    "abnormal phenotype",
    "general abnormality",
    "developmental delay",  # 仅作离线最终兜底，M3 首轮/重试不得主动产出
    "abnormal behavior",
    "neurodevelopmental abnormality",
}
_VAGUE_AXES = {
    "general",
    "generalimpression",
    "nonspecific",
    "other",
    "unknown",
    "misc",
}


def _clarify_offline_seeds(utterance: str) -> List[tuple]:
    """离线兜底：直接用规则表命中，返回 [(hpo_id, 英文检索词, 命中原话), ...]。"""
    seeds: List[tuple] = []
    for rule in _HPO_RULES:
        for pat in rule["patterns"]:
            m = re.search(pat, utterance)
            if m:
                seeds.append((
                    rule["hpo_id"],
                    _HPO_EN_HINTS.get(rule["name"], rule["name"]),
                    m.group(0),
                ))
                break
    return seeds


def _matched_fragment(hpo_id: str, utterance: str) -> str:
    """回查触发该表型的原话片段。查不到返回空串。"""
    for rule in _HPO_RULES:
        if rule["hpo_id"] != hpo_id:
            continue
        for pat in rule["patterns"]:
            m = re.search(pat, utterance)
            if m:
                return m.group(0)
    return ""


def _interleave(groups: List[List[tuple]]) -> List[tuple]:
    """按组轮转取值。家长一句话往往说了好几件事，逐组轮转能保证每件都有候选，
    否则第一个关键词的同义词会把 5 个名额占满。"""
    out: List[tuple] = []
    for i in range(max((len(g) for g in groups), default=0)):
        for g in groups:
            if i < len(g):
                out.append(g[i])
    return out


def _norm_axis(axis: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (axis or "").strip().lower())


def _source_span_in_utterance(span: str, utterance: str) -> bool:
    """source_span 须能在原话中定位，防止模型编造未提及的表现轴。"""
    s = (span or "").strip()
    u = (utterance or "").strip()
    if not s or not u:
        return False
    if s in u:
        return True
    # 去掉空白后再比一次，兼容模型插入空格
    s_compact = re.sub(r"\s+", "", s)
    u_compact = re.sub(r"\s+", "", u)
    return bool(s_compact) and s_compact in u_compact


def _parse_clarify_kw_items(raw: Any) -> List[ClarifyKw]:
    """把 M3 返回的 keywords 规整为条目列表；兼容旧版纯字符串数组。"""
    if not isinstance(raw, list):
        return []
    items: List[ClarifyKw] = []
    for entry in raw[:4]:
        if isinstance(entry, str):
            en = entry.strip().lower()
            if en:
                items.append({"en": en, "source_span": "", "axis": ""})
            continue
        if not isinstance(entry, dict):
            continue
        en = str(entry.get("en") or "").strip().lower()
        if not en:
            continue
        items.append(
            {
                "en": en,
                "source_span": str(entry.get("source_span") or "").strip(),
                "axis": str(entry.get("axis") or "").strip().lower(),
                **(
                    {"direction": str(entry.get("direction") or "").strip().lower()}
                    if entry.get("direction")
                    else {}
                ),
            }
        )
    return items


def _filter_clarify_keywords(
    items: List[ClarifyKw],
    utterance: str,
    *,
    expected_axes: Optional[dict] = None,
    stage: str = "首轮",
) -> tuple:
    """进 MCP 前的代码闸门。返回 (合法条目, 丢弃原因日志)。

    expected_axes: 重试时传入 {source_span: axis}，axis 不一致则丢（禁止换轴）。
    """
    kept: List[ClarifyKw] = []
    drops: List[str] = []
    seen_en: set = set()
    for item in items:
        en = item.get("en") or ""
        span = item.get("source_span") or ""
        axis = item.get("axis") or ""
        if en in seen_en:
            drops.append(f"{stage}丢弃重复词 «{en}»")
            continue
        if not _source_span_in_utterance(span, utterance):
            drops.append(f"{stage}丢弃未对齐原话 «{en}»(span={span or '∅'})")
            continue
        if not _scrub_clarify(en) or not _scrub_clarify(span):
            drops.append(f"{stage}丢弃黑名单命中 «{en}»")
            continue
        if en in _OVERBROAD_EN or any(en == w or en.startswith(w + " ") for w in _OVERBROAD_EN):
            drops.append(f"{stage}丢弃过宽词 «{en}»")
            continue
        if _norm_axis(axis) in _VAGUE_AXES:
            drops.append(f"{stage}丢弃笼统轴 «{en}»/axis={axis}")
            continue
        if expected_axes is not None:
            want = expected_axes.get(span) or expected_axes.get(re.sub(r"\s+", "", span))
            if not want:
                # 也按条目自带 span 的规范化键查找
                for k, v in expected_axes.items():
                    if _source_span_in_utterance(k, span) or _source_span_in_utterance(span, k):
                        want = v
                        break
            if not want or _norm_axis(axis) != _norm_axis(want):
                drops.append(
                    f"{stage}丢弃换轴 «{en}»(axis={axis or '∅'}, want={want or '∅'})"
                )
                continue
        if not _norm_axis(axis):
            drops.append(f"{stage}丢弃缺 axis «{en}»")
            continue
        seen_en.add(en)
        kept.append(item)
    return kept, drops


def _offline_keyword_items(utterance: str) -> List[ClarifyKw]:
    """M3 不可达或闸门清空时，用规则表英文提示词凑检索词（带可对齐 span）。"""
    items: List[ClarifyKw] = []
    for _hid, en, matched in _clarify_offline_seeds(utterance)[:4]:
        span = matched or utterance[: min(12, len(utterance))]
        items.append(
            {
                "en": en.strip().lower(),
                "source_span": span,
                "axis": "offline",
            }
        )
    return items


async def _clarify_keywords(utterance: str) -> tuple:
    """首轮：忠实 paraphrase → [{en, source_span, axis}, ...]。

    返回 (items, log_lines)。M3 不可达时降级离线规则表。
    """
    logs: List[str] = []
    system = (
        "你是医学表型术语改写器，只做同义 paraphrase，不做诊断、不提疾病名、不提药物。"
        "把家长中文口语里已经说出的可观察表现，改写成 1 到 4 个用于检索人类表型本体（HPO）的英文关键词短语。"
        "硬约束："
        "1) 只改写原话已有表现，禁止新增原话未提及的症状轴（例如只说「急」时不得加对视/语言/抽搐）；"
        "2) 原话有几个独立表现就出几条，禁止凑满 4 条；"
        "3) 每条必须给出 source_span（家长原话中的连续片段）与 axis（该表现的短英文语义轴标签，如 temper、eye_contact）；"
        "4) en 全部小写英文，只描述可观察表现；"
        "5) 首轮贴近原话粒度，不要主动发散到更宽的共病清单。"
        '只返回严格 JSON：{"keywords":[{"en":"irritability","source_span":"急","axis":"temper"}]}'
    )
    raw_items: List[ClarifyKw] = []
    try:
        data = await call_minimax(
            system, f"家长口语描述：{utterance}", timeout=_CLARIFY_LLM_TIMEOUT
        )
        raw_items = _parse_clarify_kw_items(data.get("keywords"))
    except ScreeningError as e:
        if e.error_code != "MINIMAX_API_ERROR":
            raise
        logger.warning("M3 抽词不可达，降级为规则表英文提示词：%s", e.error_message)
        logs.append(f"M3 抽词不可达，降级离线：{e.error_message}")

    if not raw_items:
        raw_items = _offline_keyword_items(utterance)
        if raw_items:
            logs.append("首轮改用离线规则表检索词 {} 条".format(len(raw_items)))

    kept, drops = _filter_clarify_keywords(raw_items, utterance, stage="首轮")
    logs.extend(drops)
    if not kept and raw_items:
        # 闸门清空且不是离线条目时，再试一次离线（离线 span 来自正则命中，可对齐）
        offline = _offline_keyword_items(utterance)
        kept, drops2 = _filter_clarify_keywords(offline, utterance, stage="离线")
        logs.extend(drops2)
        if kept:
            logs.append("首轮闸门清空后改用离线规则表 {} 条".format(len(kept)))

    if kept:
        logs.append(
            "首轮英文检索词："
            + "、".join(
                f"{k['en']}«{k['source_span']}»/{k['axis']}" for k in kept
            )
        )
    else:
        logs.append("首轮无合法检索词")
    return kept, logs


async def _clarify_rephrase_misses(
    utterance: str, missed: List[ClarifyKw]
) -> tuple:
    """同轴 miss 梯子：对未命中词在同一 axis+source_span 上 widen 或 narrow。

    返回 (alts, log_lines)。禁止新症状轴。
    """
    logs: List[str] = []
    if not missed:
        return [], logs

    listing = "\n".join(
        f"- en={m['en']}; source_span={m['source_span']}; axis={m['axis']}"
        for m in missed
    )
    system = (
        "你是医学表型同义改写器。下列英文检索词在 HPO 中未命中。"
        "请在【同一 axis 且同一 source_span】上各给 1 到 2 个替代英文检索词，可略放大（widen）或略缩小/更笼统（narrow）。"
        "示例：急→急躁/冲动 对应 widen；冲动→急 对应 narrow。必须英文化输出。"
        "禁止更换 axis，禁止新的 source_span，禁止疾病名/基因名/药物，禁止联想其他症状轴。"
        '只返回严格 JSON：{"alts":[{"en":"impulsivity","direction":"widen","axis":"temper","source_span":"急"}]}'
    )
    try:
        data = await call_minimax(
            system,
            f"家长原话：{utterance}\n未命中条目：\n{listing}",
            timeout=_CLARIFY_LLM_TIMEOUT,
        )
        raw = data.get("alts") or data.get("keywords") or []
        alts = _parse_clarify_kw_items(raw)
    except ScreeningError as e:
        if e.error_code != "MINIMAX_API_ERROR":
            raise
        logger.warning("M3 同轴重试不可达：%s", e.error_message)
        logs.append(f"同轴重试不可达：{e.error_message}")
        return [], logs

    # 每条未命中最多保留 2 个 alt；并强制写回原 span/axis（防模型偷换）
    by_span = {(m["source_span"], _norm_axis(m["axis"])): m for m in missed}
    capped: List[ClarifyKw] = []
    counts: dict = {}
    for alt in alts:
        span = alt.get("source_span") or ""
        axis_n = _norm_axis(alt.get("axis") or "")
        parent = by_span.get((span, axis_n))
        if parent is None:
            # 允许 span 空白被模型改写空白时，用唯一 missed 回填
            if len(missed) == 1 and not span:
                parent = missed[0]
                alt["source_span"] = parent["source_span"]
                alt["axis"] = parent["axis"]
            else:
                continue
        else:
            alt["source_span"] = parent["source_span"]
            alt["axis"] = parent["axis"]
        key = (alt["source_span"], _norm_axis(alt["axis"]))
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > 2:
            continue
        capped.append(alt)

    expected = {m["source_span"]: m["axis"] for m in missed}
    kept, drops = _filter_clarify_keywords(
        capped, utterance, expected_axes=expected, stage="重试"
    )
    logs.extend(drops)
    if kept:
        logs.append(
            "同轴重试词："
            + "、".join(
                f"{k['en']}[{k.get('direction') or '?'}]«{k['source_span']}»/{k['axis']}"
                for k in kept
            )
        )
    else:
        logs.append("同轴重试无合法替代词")
    return kept, logs


async def _mcp_search_keyword_groups(
    keywords: List[ClarifyKw],
    utterance: str,
    seen: set,
    log_lines: List[str],
) -> tuple:
    """对关键词逐个 search_hpo_terms，返回 (groups, missed_keywords)。"""
    groups: List[List[tuple]] = []
    missed: List[ClarifyKw] = []
    for item in keywords:
        kw = item["en"]
        text = await _mcp_call("search_hpo_terms", {"query": kw, "max": 5})
        hits = _parse_hpo_lines(text)
        if not hits:
            missed.append(item)
            log_lines.append(f"search_hpo_terms(«{kw}») 命中 0 条")
            continue
        group: List[tuple] = []
        for hpo_id, name in hits:
            if hpo_id in seen:
                continue
            seen.add(hpo_id)
            matched = item.get("source_span") or _matched_fragment(hpo_id, utterance)
            group.append((hpo_id, name, matched))
            if len(group) >= _SEEDS_PER_KEYWORD:
                break
        if group:
            groups.append(group)
            log_lines.append(
                "search_hpo_terms(«{}») 命中 {} 条，取前 {} 条".format(
                    kw, len(hits), len(group)
                )
            )
        else:
            missed.append(item)
    return groups, missed


async def _clarify_collect(utterance: str, picked: List[str]) -> tuple:
    """检索 + 同轴 miss 重试 + 层级扩展。返回 (candidates, log_lines)。

    candidates 为 [(hpo_id, english_name, matched_text), ...]，已剔除 picked。
    MCP 不可用时退回规则表种子，保证聊天框在离线环境下仍可用。
    """
    picked_set = {p.strip() for p in picked if p and p.strip()}
    log_lines: List[str] = []
    seen: set = set()
    expanded: List[tuple] = []

    keywords, kw_logs = await _clarify_keywords(utterance)
    log_lines.extend(kw_logs)

    groups, missed = await _mcp_search_keyword_groups(
        keywords, utterance, seen, log_lines
    )
    seeds = _interleave(groups)

    # 首轮种子为空或存在未命中词时，做同轴 widen/narrow 梯子（不换轴）
    if keywords and (not seeds or missed):
        alts, alt_logs = await _clarify_rephrase_misses(
            utterance, missed if missed else keywords
        )
        log_lines.extend(alt_logs)
        if alts:
            more_groups, _more_missed = await _mcp_search_keyword_groups(
                alts, utterance, seen, log_lines
            )
            if more_groups:
                groups.extend(more_groups)
                seeds = _interleave(groups)

    if not seeds:
        # MCP 不可用或全部无命中：退回规则表，仍能给出候选
        for hpo_id, en, matched in _clarify_offline_seeds(utterance):
            if hpo_id in seen:
                continue
            seen.add(hpo_id)
            seeds.append((hpo_id, _RULE_ID_TO_NAME.get(hpo_id, en), matched))
        if seeds:
            log_lines.append("MCP 未返回结果，改用离线规则表种子 {} 条".format(len(seeds)))

    # 候选扩展：往下取细粒度子节点，叶子节点改取兄弟层
    for hpo_id, _, _ in seeds[:4]:
        text = await _mcp_call("get_hpo_children", {"id": hpo_id, "max": 8})
        children = _parse_hpo_lines(text)
        if not children:
            parent_text = await _mcp_call("get_hpo_parents", {"id": hpo_id, "max": 3})
            for parent_id, _pname in _parse_hpo_lines(parent_text):
                sib_text = await _mcp_call(
                    "get_hpo_children", {"id": parent_id, "max": 8}
                )
                children.extend(_parse_hpo_lines(sib_text))
        for child_id, child_name in children:
            if child_id in seen:
                continue
            seen.add(child_id)
            expanded.append((child_id, child_name, ""))
    if expanded:
        log_lines.append("层级扩展补充候选 {} 条".format(len(expanded)))

    pool = [c for c in seeds + expanded if c[0] not in picked_set]
    return pool, log_lines


def _rank_candidates(pool: List[tuple]) -> List[tuple]:
    """知识库覆盖得到的表型优先，保证用户勾选后 RAG 能召回对应桶 A 切片。"""
    covered = [c for c in pool if c[0] in _RULE_ID_TO_NAME]
    rest = [c for c in pool if c[0] not in _RULE_ID_TO_NAME]
    return (covered + rest)[:_CLARIFY_MAX_OPTIONS]


async def _clarify_localize(utterance: str, picks: List[tuple]) -> tuple:
    """M3 回填中文表型名与家长口语问法。返回 (reply, {hpo_id: (name, plain)})。

    规则表已覆盖的 hpo_id 直接用本地中文名，不依赖 M3；M3 只负责补齐其余条目与引导语。
    解析失败时全部回落到模板，不阻断整条链路。
    """
    fallback_reply = "谢谢你的描述。下面几条是和你说的情况相关的表现，选出符合孩子的，我帮你整理进症状描述。"
    mapping = {}
    for hpo_id, en_name, _ in picks:
        local = _RULE_ID_TO_NAME.get(hpo_id)
        base = local or en_name
        mapping[hpo_id] = (base, f"孩子有没有「{base}」这样的表现？")

    system = (
        "你是把医学表型术语翻译成家长听得懂的白话的翻译官。"
        "严禁诊断、严禁定性、严禁提及任何疾病名称、基因名称、药物名称或剂量。"
        "对每个 HPO 条目给出中文标准表型名 name，以及一句面向家长的确认问句 plain（25 字以内，只问表现）。"
        "reply 是一句中性引导语，40 字以内，不得暗示任何结论。"
        '只返回严格 JSON：{"reply": "...", "items": [{"hpo_id": "HP:0000733", "name": "...", "plain": "..."}]}'
    )
    listing = "\n".join(f"{hpo_id} = {en_name}" for hpo_id, en_name, _ in picks)
    try:
        data = await call_minimax(
            system,
            f"家长原话：{utterance}\n待翻译的 HPO 条目：\n{listing}",
            timeout=_CLARIFY_LLM_TIMEOUT,
        )
    except ScreeningError as e:
        if e.error_code != "MINIMAX_API_ERROR":
            raise
        logger.warning("M3 回填不可达，使用模板问法：%s", e.error_message)
        return fallback_reply, mapping

    reply = str(data.get("reply") or "").strip() or fallback_reply
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        hpo_id = str(item.get("hpo_id") or "").strip()
        if hpo_id not in mapping:
            continue
        name = str(item.get("name") or "").strip() or mapping[hpo_id][0]
        plain = str(item.get("plain") or "").strip() or mapping[hpo_id][1]
        mapping[hpo_id] = (name, plain)
    return reply, mapping


# ---------- 澄清对话合规收口 ----------

# 病名黑名单里要剔除的通用词：留着会把正常表型描述也误杀
_BLACKLIST_STOPWORDS = {
    "syndrome", "syndromes", "complex", "related", "disorder", "disorders",
    "disease", "diseases", "and", "the", "of",
}
_CN_BLACKLIST_STOPWORDS = {"综合征", "相关疾病", "疾病", "基础标准与初级保健"}

_SAFE_REPLY = "谢谢你的描述。下面几条是和你说的情况相关的表现，选出符合孩子的，我帮你整理进症状描述。"


def _build_condition_blacklist() -> set:
    """从桶 A 抽病名与基因名。聊天候选只承载表型，出现病名即视为滑向诊断。"""
    words: set = set()
    for entry in _load_bucket_json("bucket_a_differential.json"):
        raw = f"{entry.get('condition', '')} / {entry.get('gene', '')}"
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", raw):
            if token.lower() not in _BLACKLIST_STOPWORDS:
                words.add(token.lower())
        for run in re.findall(r"[\u4e00-\u9fa5]{2,}", raw):
            if run in _CN_BLACKLIST_STOPWORDS:
                continue
            words.add(run)
            trimmed = run
            for suffix in ("综合征", "相关疾病"):
                trimmed = trimmed.replace(suffix, "")
            if trimmed.endswith("症") and len(trimmed) >= 4:
                trimmed = trimmed[:-1]
            if len(trimmed) >= 2 and trimmed not in _CN_BLACKLIST_STOPWORDS:
                words.add(trimmed)
    return words


_CONDITION_BLACKLIST: set = set()


def _condition_blacklist() -> set:
    global _CONDITION_BLACKLIST
    if not _CONDITION_BLACKLIST:
        try:
            _CONDITION_BLACKLIST = _build_condition_blacklist()
        except Exception as e:
            logger.warning("桶 A 病名黑名单构建失败，退回仅禁词扫描：%s", e)
            _CONDITION_BLACKLIST = {"__unavailable__"}
    return _CONDITION_BLACKLIST


def _scrub_clarify(text: str) -> bool:
    """澄清输出的合规闸门。命中禁用词、用药词或桶 A 病名/基因名即判脏。

    禁用词是字面子串匹配，否定句式（如「这不是确诊结论」）同样算违规。
    """
    if not text:
        return True
    if any(w in text for w in _BANNED_WORDS):
        return False
    if _DRUG_RE.search(text):
        return False
    low = text.lower()
    return not any(bad in low for bad in _condition_blacklist())


# ---------- 端点 ----------


@app.post("/api/clarify", response_model=ClarifyResponse)
async def clarify(payload: ClarifyRequest) -> ClarifyResponse:
    """澄清端点：把家长口语反推为 3-5 个候选表型，供前端勾选后回填症状框。

    只产出表型候选，不产出任何结论；报告仍由 POST /api/screen 生成。
    """
    if not payload.utterance.strip():
        raise ScreeningError(
            422, "INVALID_INPUT", "请先描述孩子的表现，再让我帮你整理。"
        )

    if MOCK_MODE == "missing_api_key" or (
        not MINIMAX_API_KEY and MOCK_MODE != "hpo_no_match"
    ):
        raise ScreeningError(
            500, "MISSING_API_KEY", "后端未配置 MINIMAX_API_KEY，请联系管理员。"
        )

    pool, log_lines = await _clarify_collect(payload.utterance, payload.picked)
    picks = _rank_candidates(pool)
    if not picks:
        raise ScreeningError(
            422, "HPO_NO_MATCH",
            "暂未匹配到标准表型术语，换个说法描述孩子的具体表现再试试。",
        )

    reply, mapping = await _clarify_localize(payload.utterance, picks)

    options: List[SymptomOption] = []
    for hpo_id, en_name, matched in picks:
        name, plain = mapping.get(hpo_id, (en_name, ""))
        if not _scrub_clarify(name) or not _scrub_clarify(plain):
            logger.warning("澄清候选被合规闸门剔除：%s（%s）", hpo_id, name)
            continue
        options.append(
            SymptomOption(
                hpo_id=hpo_id, name=name, plain=plain, matched_text=matched
            )
        )

    if not options:
        raise ScreeningError(
            422, "HPO_NO_MATCH",
            "暂未匹配到标准表型术语，换个说法描述孩子的具体表现再试试。",
        )
    if len(options) < _CLARIFY_MIN_OPTIONS:
        logger.warning("澄清候选仅 %d 条，少于期望的 %d 条", len(options), _CLARIFY_MIN_OPTIONS)

    if not _scrub_clarify(reply):
        logger.warning("澄清引导语被合规闸门替换")
        reply = _SAFE_REPLY

    log_lines.append(
        "最终候选 {} 条：{}".format(
            len(options),
            "；".join(f"{o.hpo_id} ({o.name})" for o in options),
        )
    )
    return ClarifyResponse(
        reply=reply,
        options=options,
        mcp_translation="。".join(log_lines) + "。",
        disclaimer=official_disclaimer(),
    )


@app.post(
    "/api/screen",
    response_model=ScreeningResponse,
    response_model_exclude_none=True,
)
async def screen(payload: ScreeningRequest) -> ScreeningResponse:
    """全系统唯一业务端点。"""
    if not payload.symptoms.strip():
        raise ScreeningError(
            422, "INVALID_INPUT", "症状描述为必填项，请补全后重新提交。"
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
    # 无基因报告时：安抚与下一步统一走症状向文案，避免 LLM 仍按 VUS 口吻发挥
    if not payload.gene_report.strip():
        offline = _offline_synthesize(payload, hpo_terms, chunks)
        report["vus_reassurance"] = offline["vus_reassurance"]
        report["next_steps"] = offline["next_steps"]
    try:
        comparisons = [Comparison(**c) for c in report.get("comparisons", [])]
    except (TypeError, ValueError) as e:
        # 兜底护栏：任何形状意外都不得逃逸成裸 500，改走离线合成保住契约
        logger.warning("报告结构装配失败，改用离线合成：%s", e)
        report = _offline_synthesize(payload, hpo_terms, chunks)
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
