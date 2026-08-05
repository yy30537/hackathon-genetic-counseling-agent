"""ASD-GenDecoder 前端：单文件 Streamlit 应用「静谧证据台」。

实现遵循 docs/UI_BLUEPRINT.md §8：函数名与调用顺序一字不差。
启动：streamlit run app.py（需后端 uvicorn 进程同时运行）
"""
import html
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
import streamlit as st

from config import BACKEND_URL  # noqa: F401  通过 config 统一读 .env

# ---------- 常量与工具 ----------

USE_MOCK: bool = False  # 演示态可改 True

BACKEND_URL_LOCAL: str = BACKEND_URL
CIRCLED = "①②③④⑤⑥⑦⑧⑨"

FIXTURES_DIR = Path(__file__).resolve().parent / "data" / "fixtures"
BUCKET_C_PATH = Path(__file__).resolve().parent / "data" / "knowledge" / "bucket_c_compliance.json"

# 路演示例：合成数据，非真实病例（文案对齐 data/test_cases/tc_01–tc_05）
EXAMPLE_CASES: List[Dict[str, str]] = [
    {
        "label": "Rett / MECP2",
        "symptoms": (
            "我女儿快3岁了。她1岁多的时候明明会喊爸爸妈妈，还会指东西要，"
            "可是从1岁半开始，会说的词一个一个都没了，现在基本上不说话了。"
            "最让我心慌的是她的手，以前会自己抓饼干吃，现在整天在胸前搓来搓去、"
            "绞来绞去，像在洗手一样，停都停不下来，也不会拿东西了。"
            "体检说她头围长得比同龄孩子慢。走路也是晃晃悠悠的，两只脚岔得很开。"
            "有时候醒着的时候会突然喘得很急，过一会儿又憋着不呼吸。"
        ),
        "gene_report": (
            "全外显子组测序（WES）报告：检出 MECP2 基因杂合错义变异 "
            "c.455C>G (p.Pro152Arg)，ACMG 分级为临床意义未明（VUS）。"
            "未检出其他与临床表型相关的致病或可能致病变异。"
        ),
    },
    {
        "label": "安格曼 / UBE3A",
        "symptoms": (
            "孩子4岁了，一个字都不会说，只会啊啊叫。他特别爱笑，一天到晚咯咯咯地笑，"
            "有时候一点小事就笑得停不下来，谁看了都说这孩子真开心，但我们知道不对劲。"
            "走路的时候两条腿分得特别开，手老是举得高高的、胳膊肘弯着，看着像小木偶。"
            "晚上几乎不睡，折腾到凌晨两三点。上个月还抽过一次，眼睛往上翻，手脚僵硬。"
        ),
        "gene_report": (
            "基因检测报告：15q11.2-q13 区域母源片段缺失，UBE3A 基因表达缺失。"
            "甲基化分析异常。"
        ),
    },
    {
        "label": "脆性 X / FMR1",
        "symptoms": (
            "我儿子6岁，从小就不肯看人的眼睛，你跟他说话他就把头扭开，"
            "有生人来家里他能躲到桌子底下不出来。高兴或者紧张的时候就使劲拍手，"
            "一拍好几分钟。他脸比别的孩子长一些，耳朵也特别大，额头挺凸的。"
            "老师说他一节课都坐不住，屁股像长了钉子，写两个字就要站起来跑。"
            "而且特别容易焦虑，换个座位、走另一条路回家都能让他崩溃大哭。"
        ),
        "gene_report": (
            "FMR1 基因检测：CGG 三核苷酸重复次数 > 200 次，呈全突变范围，伴异常甲基化。"
        ),
    },
    {
        "label": "结节性硬化 / TSC2",
        "symptoms": (
            "宝宝现在1岁8个月。他身上有好几块白色的斑，形状有点像柳树叶子，"
            "后背和大腿上加起来能数出五六块，出生没多久就有了，一直没消。"
            "大概7个月大的时候开始一阵一阵地点头、两只胳膊往前抱，一次连着好几十下，"
            "我们一开始以为他是困了。最近发现他会的东西变少了，本来会拍手再见，"
            "现在不会了，叫名字也不太理人。"
        ),
        "gene_report": (
            "全外显子组测序：TSC2 基因杂合变异 c.4375C>T (p.Arg1459Trp)，"
            "临床意义未明（VUS）。"
        ),
    },
    {
        "label": "阴性对照 / ASD",
        "symptoms": (
            "孩子3岁半，不太跟小朋友玩，别人叫他名字经常没反应，但听到广告音乐就会跑过来。"
            "喜欢把小汽车排成一长排，谁动一下就大哭。说话会说，但常常是重复别人的话，"
            "你问他要不要吃苹果，他就跟着说要不要吃苹果。喜欢转圈圈，也喜欢盯着洗衣机看很久。"
            "身体上没什么特别的，个子体重都正常，没抽过筋。"
        ),
        "gene_report": (
            "全外显子组测序（WES）报告：未检出与临床表型相关的致病性或可能致病性变异。"
            "检出 3 个临床意义未明变异（VUS），均位于目前与神经发育疾病无明确关联的基因。"
        ),
    },
]

# §7 全文 CSS（注入一次）
CSS: str = """
<style>
:root{
  --bg-canvas:#FAFAF7; --bg-surface:#FFFFFF; --bg-panel:#F4F3EE;
  --brand:#5B8C85; --brand-strong:#47726C; --brand-soft:#E4EFEC;
  --text-primary:#1F2321; --text-muted:#7A807C; --text-muted-strong:#636965;
  --border:#E6E4DD;
  --bucket-a:#5B8C85; --bucket-a-soft:#E4EFEC;
  --bucket-b:#7C6BA8; --bucket-b-soft:#EDE9F5;
  --bucket-c:#C08A3E; --bucket-c-soft:#F7EDDC;
  --radius:12px; --shadow:0 1px 3px rgba(31,35,33,.06);
  --font-sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Microsoft YaHei",Inter,sans-serif;
  --font-mono:"JetBrains Mono","SF Mono",Menlo,Consolas,monospace;
}
html, body, [class*="css"]{ font-family:var(--font-sans); color:var(--text-primary); }
.stApp{ background:var(--bg-canvas); }
.block-container{ max-width:1180px; padding:32px 32px 64px; }
#MainMenu, footer{ visibility:hidden; }
.ced-header{ border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:24px; }
.ced-title{ font-size:24px; line-height:1.4; font-weight:600; }
.ced-sub{ font-size:16px; line-height:1.8; color:var(--text-muted); margin-top:4px; }
.ced-section{ margin-bottom:32px; }
.ced-section-title{ font-size:18px; line-height:1.5; font-weight:600; margin-bottom:12px; }
.ced-note{ font-size:13px; line-height:1.6; color:var(--text-muted-strong); }
.ced-card{ background:var(--bg-surface); border:1px solid var(--border);
           border-radius:var(--radius); box-shadow:var(--shadow); padding:20px; margin-bottom:16px; }
.ced-quote{ border-left:3px solid var(--bucket-b); padding-left:16px;
            font-size:17px; line-height:1.9; }
.ced-hpo{ width:100%; border-collapse:collapse; }
.ced-hpo th{ text-align:left; font-size:13px; font-weight:400; color:var(--text-muted-strong);
             padding:0 0 8px; border-bottom:1px solid var(--border); }
.ced-hpo td{ padding:12px 0; border-bottom:1px solid var(--border);
             font-size:16px; line-height:1.8; vertical-align:top; }
.ced-hpo tr:last-child td{ border-bottom:none; }
.ced-hpo .ced-std{ font-weight:600; }
.ced-hpoid{ font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); margin-left:8px; }
.ced-cmp-head{ display:flex; align-items:center; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.ced-cmp-title{ font-size:18px; font-weight:600; }
.ced-gene{ font-family:var(--font-mono); font-size:13px; background:var(--brand-soft);
           color:var(--brand-strong); border-radius:999px; padding:2px 10px; }
.ced-anchors{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
.ced-anchor{ font-size:13px; background:var(--brand-soft); color:var(--brand-strong);
             border-radius:999px; padding:2px 10px; }
.ced-cmp-body{ font-size:16px; line-height:1.8; }
.ced-cmp-src{ margin-top:12px; padding-top:12px; border-top:1px solid var(--border);
              text-align:right; font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }
.ced-step{ display:flex; gap:12px; margin-bottom:12px; }
.ced-step-idx{ flex:0 0 20px; height:20px; margin-top:4px; border-radius:4px;
               background:var(--brand-soft); color:var(--brand-strong);
               font-size:13px; text-align:center; line-height:20px; }
.ced-step-txt{ font-size:16px; line-height:1.8; }
.ced-panel{ background:var(--bg-panel); border-radius:var(--radius); padding:20px; }
.ced-chunk{ background:var(--bg-surface); border:1px solid var(--border);
            border-radius:var(--radius); padding:16px; margin-bottom:12px; }
.ced-chunk-head{ display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap; }
.ced-refno{ font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }
.ced-tag{ font-size:13px; border-radius:4px; padding:2px 8px; }
.ced-tag-a{ background:var(--bucket-a-soft); color:var(--bucket-a); }
.ced-tag-b{ background:var(--bucket-b-soft); color:var(--bucket-b); }
.ced-tag-c{ background:var(--bucket-c-soft); color:var(--bucket-c); }
.ced-origin{ font-size:13px; background:var(--bg-panel); color:var(--text-muted-strong);
             border-radius:4px; padding:2px 8px; }
.ced-chunk-src{ margin-left:auto; font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }
.ced-chunk-text{ font-size:13px; line-height:1.7; }
.ced-chunk-text summary{ cursor:pointer; color:var(--brand-strong); }
.ced-disclaimer{ background:var(--bucket-c-soft); border-left:4px solid var(--bucket-c);
                 border-radius:var(--radius); padding:20px; margin-top:32px; }
.ced-disclaimer-label{ font-size:13px; font-weight:600; color:var(--bucket-c); margin-bottom:8px; }
.ced-disclaimer-body{ font-size:16px; line-height:1.8; }
.ced-error{ background:var(--bucket-c-soft); border:1px solid var(--bucket-c);
            border-radius:var(--radius); padding:20px; }
.ced-error-title{ font-size:18px; font-weight:600; color:var(--bucket-c); margin-bottom:8px; }
.stButton>button, .stFormSubmitButton>button{
  background:var(--brand); color:#fff; border:none; border-radius:var(--radius);
  font-weight:600; padding:10px 20px; }
.stButton>button:hover, .stFormSubmitButton>button:hover{ background:var(--brand-strong); color:#fff; }
/* 示例填充与「加入症状描述」是次要动作，弱化为描边样式，不与主提交按钮抢视觉权重 */
.stButton>button[kind="secondary"]{ background:var(--bg-surface); color:var(--brand-strong);
  border:1px solid var(--border); font-weight:500; font-size:13px; padding:6px 12px; }
.stButton>button[kind="secondary"]:hover{ background:var(--brand-soft);
  color:var(--brand-strong); border-color:var(--brand); }
.stChatMessage{ background:var(--bg-surface); border:1px solid var(--border);
                border-radius:var(--radius); box-shadow:var(--shadow); margin-bottom:12px; }
.stChatMessage p{ font-size:16px; line-height:1.8; }
.ced-examples{ margin-bottom:12px; }
.ced-examples-label{ font-size:13px; line-height:1.6; color:var(--text-muted-strong); margin-bottom:8px; }
.stTextArea textarea{ background:var(--bg-surface); border:1px solid var(--border);
  border-radius:var(--radius); font-size:16px; line-height:1.8; color:var(--text-primary); }
.stTextArea textarea:focus{ border-color:var(--brand); box-shadow:none; }
.stTextArea textarea[aria-label="粘贴基因报告文本"]{ font-family:var(--font-mono); font-size:13px; line-height:1.7; }
div[data-baseweb="notification"]{ background:var(--bucket-c-soft) !important;
  border-left:4px solid var(--bucket-c) !important; color:var(--text-primary) !important; }
</style>
"""


@st.cache_data
def load_fallback_disclaimer() -> str:
    """非成功态 disclaimer 来源：读桶 C 的 is_disclaimer 条目 text。"""
    try:
        entries = json.loads(BUCKET_C_PATH.read_text(encoding="utf-8"))
        for e in entries:
            if e.get("is_disclaimer"):
                return e["text"]
        return entries[0]["text"] if entries else ""
    except Exception:
        return ""


def load_mock(kind: str) -> dict:
    """读取 data/fixtures/mock_response.{kind}.json。"""
    p = FIXTURES_DIR / f"mock_response.{kind}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def call_backend(symptoms: str, gene_report: str) -> Tuple[str, Dict[str, Any]]:
    """POST 到后端,返回 (stage, payload_or_err)。stage ∈ {"success","error"}。"""
    if USE_MOCK:
        return "success", load_mock("success")
    try:
        r = requests.post(
            f"{BACKEND_URL_LOCAL}/api/screen",
            json={"symptoms": symptoms, "gene_report": gene_report},
            timeout=120,
        )
    except requests.exceptions.ConnectionError:
        return "error", {"error_code": "CONNECTION_ERROR", "error_message": "无法连接后端服务，请确认已执行 uvicorn main:app --port 8000。"}
    except requests.exceptions.Timeout:
        return "error", {"error_code": "TIMEOUT", "error_message": "请求超时，请稍后重试。"}
    except Exception as e:
        return "error", {"error_code": "UNKNOWN", "error_message": f"请求异常：{type(e).__name__}"}

    if r.status_code == 200:
        try:
            return "success", r.json()
        except ValueError:
            return "error", {"error_code": "BAD_JSON", "error_message": "后端响应不是合法 JSON。"}
    try:
        body = r.json()
    except ValueError:
        body = {"error_code": "BAD_JSON", "error_message": f"HTTP {r.status_code}"}
    return "error", body


def call_clarify(utterance: str, picked: List[str]) -> Tuple[str, Dict[str, Any]]:
    """POST 到澄清端点，返回 (stage, payload_or_err)。stage ∈ {"success","error"}。

    与 call_backend 同构：前端唯一的出口仍是 HTTP，不直连模型或向量库。
    """
    try:
        r = requests.post(
            f"{BACKEND_URL_LOCAL}/api/clarify",
            json={"utterance": utterance, "picked": picked},
            timeout=120,
        )
    except requests.exceptions.ConnectionError:
        return "error", {"error_code": "CONNECTION_ERROR", "error_message": "无法连接后端服务，请确认已执行 uvicorn main:app --port 8000。"}
    except requests.exceptions.Timeout:
        return "error", {"error_code": "TIMEOUT", "error_message": "请求超时，请稍后重试。"}
    except Exception as e:
        return "error", {"error_code": "UNKNOWN", "error_message": f"请求异常：{type(e).__name__}"}

    if r.status_code == 200:
        try:
            return "success", r.json()
        except ValueError:
            return "error", {"error_code": "BAD_JSON", "error_message": "后端响应不是合法 JSON。"}
    try:
        body = r.json()
    except ValueError:
        body = {"error_code": "BAD_JSON", "error_message": f"HTTP {r.status_code}"}
    return "error", body


# ---------- 证据回溯（§5.2 算法） ----------

_GENERIC_TOKENS = {
    "genereviews", "pubmed", "aap", "acmg", "fda", "curated",
    "related", "disorders", "disorder", "syndrome", "review", "reviews",
    "the", "of", "and", "a", "an",
}


def _tokenize(s: str) -> set:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return {t for t in s.split() if t}


def _score(comparison: dict, chunk: dict) -> int:
    ct = _tokenize(chunk.get("source", ""))
    pt = _tokenize(comparison.get("source", ""))
    s = 0
    gene = comparison.get("gene") or ""
    if gene.strip():
        gene_set = _tokenize(gene)
        if gene_set and gene_set.issubset(ct):
            s += 2
    s += len((pt - _GENERIC_TOKENS) & (ct - _GENERIC_TOKENS))
    return s


def match_chunk_refs(comparisons: List[dict], chunks: List[dict]) -> List[List[int]]:
    """每张比对卡 → 命中的切片下标列表(最多 2 个,按下标升序)。"""
    out = []
    for c in comparisons:
        scores = [_score(c, ch) for ch in chunks]
        if not scores or max(scores) == 0:
            out.append([])
            continue
        best = max(scores)
        idxs = [i for i, v in enumerate(scores) if v == best]
        out.append(idxs[:2])
    return out


def _ref_label(i: int) -> str:
    return CIRCLED[i] if 0 <= i < len(CIRCLED) else f"({i+1})"


# ---------- 渲染函数（每个内部只做一次 st.markdown） ----------


def render_header() -> None:
    st.markdown(
        '<div class="ced-header">'
        '<div class="ced-title">ASD-GenDecoder · 就诊前置信息整理</div>'
        '<div class="ced-sub">帮你把孩子的表现和基因报告，翻译成可以带去门诊的语言</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_idle_hint() -> None:
    st.markdown(
        '<div class="ced-section">'
        '<div class="ced-section-title">填写下方两个输入框，生成可带去门诊的信息整理单</div>'
        '<div class="ced-note">把白话症状对应到 HPO 标准术语<br/>'
        '与文献中的鉴别锚点做客观比对<br/>'
        '整理出就诊时该带什么、该说什么</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_loading() -> None:
    st.markdown(
        '<div class="ced-section">'
        '<div class="ced-section-title">正在生成…</div>'
        '<div class="ced-note">术语标准化 (MCP)<br/>知识检索 (RAG)<br/>报告合成 (M3)</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_reassurance(text: str) -> None:
    if not text:
        return
    st.markdown(
        f'<div class="ced-section">'
        f'<div class="ced-section-title">关于「临床意义未明」，先看这段</div>'
        f'<div class="ced-quote">{html.escape(text)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_hpo_table(hpo_terms: List[dict]) -> None:
    st.markdown('<div class="ced-section-title">您的描述 → 医学术语</div>', unsafe_allow_html=True)
    if not hpo_terms:
        st.markdown('<div class="ced-note">本次未能标准化出表型术语</div>', unsafe_allow_html=True)
        return
    rows = []
    for t in hpo_terms:
        m = html.escape(t.get("matched_text") or "—")
        n = html.escape(t.get("name") or "—")
        hid = html.escape(t.get("hpo_id") or "")
        rows.append(
            f'<tr><td>「{m}」</td><td><span class="ced-std">{n}</span>'
            f'{"<span class=ced-hpoid>" + hid + "</span>" if hid else ""}</td></tr>'
        )
    st.markdown(
        '<table class="ced-hpo"><thead><tr><th>家长原话</th><th>HPO 标准术语</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table>",
        unsafe_allow_html=True,
    )


def render_comparisons(comparisons: List[dict], refs: List[List[int]]) -> None:
    st.markdown(
        '<div class="ced-section-title">需请医生一并排除的方向</div>'
        '<div class="ced-note" style="margin-bottom:12px">以下均为文献特征的客观比对，不是结论。</div>',
        unsafe_allow_html=True,
    )
    if not comparisons:
        st.markdown(
            '<div class="ced-card">'
            '<div class="ced-section-title" style="font-size:16px">本次未匹配到相关指南条目。</div>'
            '<div class="ced-note">这不代表存在问题，也不代表可以排除问题，只说明知识库里没有可比对的文献特征。请以医生面诊为准。</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return
    cards = []
    for c, ref in zip(comparisons, refs):
        cond = html.escape(c.get("condition") or "未命名比对项")
        gene = html.escape(c.get("gene") or "")
        anchors = c.get("matched_anchors") or []
        anchors_html = "".join(
            f'<span class="ced-anchor">{html.escape(a)}</span>' for a in anchors
        )
        explanation = html.escape(c.get("explanation") or "")
        source = html.escape(c.get("source") or "")
        ref_str = " ".join(_ref_label(i) for i in ref) if ref else ""
        gene_html = f'<span class="ced-gene">{gene}</span>' if gene else ""
        anchors_row = f'<div class="ced-anchors">{anchors_html}</div>' if anchors_html else ""
        src_text = f"来源：{source}" + (f" {ref_str}" if ref_str else "")
        cards.append(
            f'<div class="ced-card">'
            f'<div class="ced-cmp-head"><div class="ced-cmp-title">{cond}</div>{gene_html}</div>'
            f"{anchors_row}"
            f'<div class="ced-cmp-body">{explanation}</div>'
            f'<div class="ced-cmp-src">{html.escape(src_text)}</div>'
            f"</div>"
        )
    st.markdown("".join(cards), unsafe_allow_html=True)


def render_next_steps(steps: List[str]) -> None:
    if not steps:
        st.markdown(
            '<div class="ced-note" style="margin:8px 0">就诊建议缺失（后端未返回 next_steps，请联系管理员）。</div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown('<div class="ced-section-title">下一步就诊清单</div>', unsafe_allow_html=True)
    items = "".join(
        f'<div class="ced-step"><div class="ced-step-idx">{i+1}</div>'
        f'<div class="ced-step-txt">{html.escape(s)}</div></div>'
        for i, s in enumerate(steps)
    )
    st.markdown(items, unsafe_allow_html=True)


def render_confidence_line(value) -> None:
    if value is None:
        return
    if not isinstance(value, int) or not (0 <= value <= 100):
        return
    st.markdown(
        f'<div class="ced-section" style="margin-top:16px">'
        f'<div class="ced-note">本次筛查可信度：<span style="font-family:var(--font-mono)">{value}</span> / 100</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_error(err: dict) -> None:
    code = err.get("error_code", "")
    msg = err.get("error_message", "后端未返回错误详情")
    titles = {
        "INVALID_INPUT": ("输入还需要补全", "请先通过上方聊天勾选症状描述后再提交。"),
        "HPO_NO_MATCH": ("暂未匹配到标准表型术语", "请补充更具体的表现描述，或携带原始记录咨询儿童发育行为科。"),
        "MISSING_API_KEY": ("后端缺少模型密钥", "请检查项目根目录 .env 中的 MINIMAX_API_KEY。"),
        "MINIMAX_API_ERROR": ("模型服务暂时不可用", "这通常是限流或超时，稍后重试即可。"),
        "CONNECTION_ERROR": ("无法连接后端服务", "请确认已执行 uvicorn main:app --reload --port 8000。"),
        "TIMEOUT": ("请求超时", "请稍后重试。"),
    }
    title, hint = titles.get(code, ("请求失败", ""))
    st.markdown(
        f'<div class="ced-error">'
        f'<div class="ced-error-title">{html.escape(title)}</div>'
        f'<div class="ced-cmp-body">{html.escape(msg)}</div>'
        f'{"<div class=ced-note style=margin-top:8px>" + html.escape(hint) + "</div>" if hint else ""}'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_chat_panel(disabled: bool) -> None:
    """聊天式症状澄清：口语描述 -> 后端反推候选表型 -> 勾选后回填症状框。

    对话只存在于本次会话的内存里，不落盘、不做历史持久化（PRD W2）。
    候选只承载表型，不含任何病名，措辞由后端合规闸门把关。
    """
    st.markdown(
        '<div class="ced-section-title">先聊两句，我帮你把话变成医学表述</div>'
        '<div class="ced-note" style="margin-bottom:12px">'
        "用平常话说说孩子的表现就行。我会列出几条相关的医学表现供你确认，"
        "它们是待核对的候选描述，不是结论。"
        "</div>",
        unsafe_allow_html=True,
    )

    msgs = st.session_state.chat_msgs
    if not msgs:
        st.markdown(
            '<div class="ced-note" style="margin-bottom:12px">'
            "例如：孩子快三岁了，本来会喊爸爸妈妈，现在都不说了，整天在胸前搓手。"
            "</div>",
            unsafe_allow_html=True,
        )

    for idx, msg in enumerate(msgs):
        with st.chat_message(msg["role"]):
            if msg.get("error"):
                render_error(msg["error"])
                continue
            st.markdown(
                f'<div class="ced-cmp-body">{html.escape(msg.get("text", ""))}</div>',
                unsafe_allow_html=True,
            )
            options = msg.get("options") or []
            if not options:
                continue
            if idx != len(msgs) - 1:
                st.markdown(
                    '<div class="ced-note">'
                    + html.escape("、".join(o["name"] for o in options))
                    + "</div>",
                    unsafe_allow_html=True,
                )
                continue
            for o in options:
                st.checkbox(
                    f"{o['plain']}　（{o['name']}　{o['hpo_id']}）",
                    key=f"chat_opt_{idx}_{o['hpo_id']}",
                    disabled=disabled,
                )
            if st.button(
                "把勾选的表现加入症状描述",
                key=f"chat_apply_{idx}",
                disabled=disabled,
                use_container_width=True,
            ):
                chosen = [
                    o for o in options
                    if st.session_state.get(f"chat_opt_{idx}_{o['hpo_id']}")
                ]
                if not chosen:
                    st.warning("请先勾选至少一条符合孩子情况的表现。")
                else:
                    names = "、".join(o["name"] for o in chosen)
                    # 写入带 HPO ID，供 /api/screen 直接识别（MCP 中文名常不在离线规则表）
                    labeled = "、".join(
                        f"{o['name']}（{o['hpo_id']}）" for o in chosen
                    )
                    prev = (st.session_state.get("symptoms") or "").strip()
                    addition = f"孩子还有这些表现：{labeled}。"
                    st.session_state.symptoms = (
                        f"{prev}\n{addition}" if prev else addition
                    )
                    for o in chosen:
                        if o["hpo_id"] not in st.session_state.picked_ids:
                            st.session_state.picked_ids.append(o["hpo_id"])
                    st.session_state.chat_msgs.append({
                        "role": "assistant",
                        "text": f"已加入症状描述：{names}。你可以继续补充，或直接生成信息整理单。",
                        "options": [],
                    })
                    st.rerun()

    utterance = st.chat_input(
        "说说孩子最近的表现…", key="chat_input", disabled=disabled
    )
    if utterance and utterance.strip():
        st.session_state.chat_msgs.append(
            {"role": "user", "text": utterance.strip(), "options": []}
        )
        with st.spinner(""):
            stage, payload = call_clarify(
                utterance.strip(), st.session_state.picked_ids
            )
        if stage == "success":
            st.session_state.chat_msgs.append({
                "role": "assistant",
                "text": payload.get("reply", ""),
                "options": payload.get("options", []),
            })
            st.session_state.clarify_trace = payload.get("mcp_translation", "")
        elif (payload or {}).get("error_code") == "HPO_NO_MATCH":
            # 无命中不阻断对话：软跳过本轮，不写入 symptoms，报告自然忽略
            st.session_state.chat_msgs.append({
                "role": "assistant",
                "text": (
                    "这段描述暂时对不上标准术语，我们先跳过。"
                    "你可以换个说法，或继续描述孩子的其他表现。"
                ),
                "options": [],
            })
        else:
            st.session_state.chat_msgs.append({
                "role": "assistant", "text": "", "options": [], "error": payload,
            })
        st.rerun()

    st.markdown('<div style="margin-bottom:24px"></div>', unsafe_allow_html=True)


def render_example_buttons(disabled: bool) -> None:
    """一键填入合成示例，路演时免去现场打字。"""
    st.markdown(
        '<div class="ced-examples">'
        '<div class="ced-examples-label">示例 · 合成数据，非真实病例 — 点击填入后可再点「生成信息整理单」</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(len(EXAMPLE_CASES))
    for i, case in enumerate(EXAMPLE_CASES):
        with cols[i]:
            if st.button(
                case["label"],
                key=f"example_fill_{i}",
                disabled=disabled,
                use_container_width=True,
            ):
                st.session_state.symptoms = case["symptoms"]
                st.session_state.gene_report = case["gene_report"]
                st.session_state.gene_report_method = "粘贴基因报告文本"
                st.rerun()


def render_intake_form(disabled: bool) -> None:
    placeholder_g = (
        "全外显子测序（WES）检出 MECP2 基因错义变异 c.455C>G (p.Pro152Arg)，"
        "临床意义未明（VUS）。"
    )
    # 「孩子的情况」由聊天勾选写入 session_state.symptoms，询问页不再展示该文本框
    st.markdown(
        '<div class="ced-section-title" style="margin:16px 0 4px">附上基因报告原文（可选）</div>'
        '<div class="ced-note" style="margin-bottom:8px">没有报告也能生成整理单；填写/上传报告后，系统比对会同步参考基因报告内容。</div>',
        unsafe_allow_html=True,
    )
    # 旧会话可能残留「不添加文本」；选项已去掉，当作未选择（无基因报告）
    if st.session_state.get("gene_report_method") == "不添加文本":
        st.session_state.gene_report_method = None
    report_method = st.pills(
        "基因报告输入方式",
        ["粘贴基因报告文本", "上传基因报告PDF文件"],
        selection_mode="single",
        default=None,
        key="gene_report_method",
        disabled=disabled,
        label_visibility="collapsed",
    )
    if report_method == "粘贴基因报告文本":
        st.text_area(
            "粘贴基因报告文本",
            key="gene_report",
            height=120,
            placeholder=placeholder_g,
            disabled=disabled,
        )
    elif report_method == "上传基因报告PDF文件":
        uploaded = st.file_uploader(
            "上传基因报告 PDF（首期支持可复制文本 PDF）",
            type=["pdf"],
            key="gene_report_pdf",
            disabled=disabled,
            help="文件仅用于本次本地提取，不会保存。扫描件或图片型 PDF 暂不支持。",
        )
        if uploaded is not None:
            pdf_bytes = uploaded.getvalue()
            st.session_state.pdf_bytes = pdf_bytes
            st.session_state.pdf_name = uploaded.name
            st.caption(
                f"已选择 {uploaded.name} · {len(pdf_bytes) / 1024:.1f} KB。"
                "提交时在本地提取文本后发送（不落盘）。"
            )
        else:
            st.session_state.pdf_bytes = None
            st.session_state.pdf_name = "report.pdf"
    submitted = st.button(
        "生成信息整理单", type="primary", use_container_width=True,
        disabled=disabled, key="submit_intake",
    )
    if submitted:
        s = (st.session_state.get("symptoms") or "").strip()
        report_method = st.session_state.get("gene_report_method")
        g = (
            (st.session_state.get("gene_report") or "").strip()
            if report_method == "粘贴基因报告文本"
            else ""
        )
        pdf_bytes = (
            st.session_state.get("pdf_bytes")
            if report_method == "上传基因报告PDF文件"
            else None
        )
        if not s:
            st.warning("请填写「孩子的情况」后再提交。")
            return
        if report_method == "粘贴基因报告文本" and not g:
            st.warning("请粘贴基因报告文本，或取消该输入方式后直接提交。")
            return
        if report_method == "上传基因报告PDF文件":
            if not pdf_bytes:
                st.warning("请上传基因报告 PDF，或取消该输入方式后直接提交。")
                return
            # 本地 pypdf 抽文本 → gene_report；不改契约、不发 PDF 字节
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(pdf_bytes))
                pages = []
                for page in reader.pages:
                    pages.append(page.extract_text() or "")
                g = "\n".join(pages).strip()
            except Exception:
                st.warning(
                    "无法读取该 PDF，请改用「粘贴基因报告文本」，"
                    "或上传可选中文字的 PDF。"
                )
                return
            if not g:
                st.warning(
                    "无法从 PDF 提取文字（可能是扫描件或图片型 PDF）。"
                    "请改用粘贴，或上传可选中文本的 PDF。"
                )
                return
        st.session_state.stage = "loading"
        with st.spinner(""):
            stage, payload = call_backend(s, g)
        st.session_state.stage = stage
        st.session_state.payload = payload
        st.rerun()


def render_evidence_panel(payload: dict) -> None:
    stage = st.session_state.get("stage", "idle")
    st.markdown(
        '<div class="ced-section-title">证据来源</div>'
        '<div class="ced-note" style="margin-bottom:12px">左侧每条比对都能在这里找到出处。</div>',
        unsafe_allow_html=True,
    )
    if stage != "success" or not payload:
        trace = st.session_state.get("clarify_trace") or ""
        if trace:
            st.markdown(
                '<div class="ced-chunk">'
                '<div class="ced-chunk-head"><div class="ced-cmp-title" style="font-size:14px">澄清对话的术语检索过程 (MCP)</div></div>'
                f'<div class="ced-chunk-text">{html.escape(trace)}</div>'
                "</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            '<div class="ced-note">生成报告后，这里会列出本次引用的全部知识库原文。</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="ced-chunk">'
        '<div class="ced-chunk-head"><div class="ced-cmp-title" style="font-size:14px">术语标准化过程 (MCP)</div></div>'
        f'<div class="ced-chunk-text">{html.escape(payload.get("mcp_translation") or "—")}</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    chunks = payload.get("retrieved_chunks") or []
    if not chunks:
        st.markdown(
            '<div class="ced-chunk"><div class="ced-note">本次未检索到知识库切片</div></div>',
            unsafe_allow_html=True,
        )
        return
    bucket_label = {"A": "桶 A · 鉴别锚点", "B": "桶 B · VUS 科普", "C": "桶 C · 合规声明"}
    origin_label = {
        "curated": "精编摘要", "genereviews": "GeneReviews 原文",
        "pubmed": "PubMed 原文", "aap": "AAP 指南原文",
    }
    cards = []
    for i, ch in enumerate(chunks):
        ref = _ref_label(i)
        b = ch.get("bucket", "")
        o = ch.get("origin", "")
        src = ch.get("source", "")
        txt = ch.get("text", "")
        b_lbl = bucket_label.get(b, "未知")
        o_lbl = origin_label.get(o, "")
        b_cls = f"ced-tag ced-tag-{b.lower()}" if b in ("a", "b", "c") else "ced-tag"
        o_html = f'<span class="ced-origin">{html.escape(o_lbl)}</span>' if o_lbl else ""
        if len(txt) > 180:
            t_html = (
                f'<details class="ced-chunk-text">'
                f'<summary>展开原文</summary>'
                f'<div>{html.escape(txt)}</div></details>'
            )
        else:
            t_html = f'<div class="ced-chunk-text">{html.escape(txt or "—")}</div>'
        cards.append(
            f'<div class="ced-chunk">'
            f'<div class="ced-chunk-head">'
            f'<span class="ced-refno">{ref}</span>'
            f'<span class="{b_cls}">{html.escape(b_lbl)}</span>'
            f"{o_html}"
            f'<span class="ced-chunk-src">{html.escape(src or "—")}</span>'
            f"</div>"
            f"{t_html}"
            f"</div>"
        )
    st.markdown("".join(cards), unsafe_allow_html=True)


def render_disclaimer(text: str) -> None:
    body = text or (
        "无法加载合规声明文本，请检查 data/knowledge/bucket_c_compliance.json"
    )
    st.markdown(
        '<div class="ced-disclaimer">'
        '<div class="ced-disclaimer-label">重要声明</div>'
        f'<div class="ced-disclaimer-body">{html.escape(body)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


# ---------- 主流程 ----------


def main() -> None:
    st.set_page_config(
        page_title="ASD-GenDecoder", layout="wide", initial_sidebar_state="collapsed",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    if "stage" not in st.session_state:
        st.session_state.stage = "idle"
    if "payload" not in st.session_state:
        st.session_state.payload = None
    if "pdf_bytes" not in st.session_state:
        st.session_state.pdf_bytes = None
    if "pdf_name" not in st.session_state:
        st.session_state.pdf_name = "report.pdf"
    # 澄清对话只活在本次会话内存里，刷新即清空（PRD W2 禁止会话历史持久化）
    if "chat_msgs" not in st.session_state:
        st.session_state.chat_msgs = []
    if "picked_ids" not in st.session_state:
        st.session_state.picked_ids = []
    if "clarify_trace" not in st.session_state:
        st.session_state.clarify_trace = ""

    render_header()

    left, right = st.columns([62, 38], gap="large")

    with left:
        stage = st.session_state.stage
        payload = st.session_state.payload
        if stage == "idle":
            render_idle_hint()
        elif stage == "loading":
            render_loading()
        elif stage == "success":
            render_reassurance(payload.get("vus_reassurance", ""))
            render_hpo_table(payload.get("hpo_terms", []))
            chunks = payload.get("retrieved_chunks", [])
            comparisons = payload.get("comparisons", [])
            refs = match_chunk_refs(comparisons, chunks)
            render_comparisons(comparisons, refs)
            render_next_steps(payload.get("next_steps", []))
            render_confidence_line(payload.get("confidence_level"))
            # 报告页不展示聊天与采集区，避免问答历史干扰阅读
            act_a, act_b = st.columns(2)
            with act_a:
                if st.button("重新生成", use_container_width=True, key="restart_fresh"):
                    st.session_state.stage = "idle"
                    st.session_state.payload = None
                    st.session_state.chat_msgs = []
                    st.session_state.picked_ids = []
                    st.session_state.symptoms = ""
                    st.session_state.gene_report = ""
                    st.session_state.gene_report_method = None
                    st.session_state.clarify_trace = ""
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_name = "report.pdf"
                    st.rerun()
            with act_b:
                if st.button(
                    "补充孩子表现或迹象",
                    use_container_width=True,
                    key="resume_intake",
                ):
                    st.session_state.stage = "idle"
                    st.rerun()
        elif stage == "error":
            render_error(payload or {})

        if stage != "success":
            render_chat_panel(disabled=(stage == "loading"))
            render_intake_form(disabled=(stage == "loading"))

    with right:
        render_evidence_panel(st.session_state.payload or {})

    disclaimer_text = ""
    if st.session_state.stage == "success" and st.session_state.payload:
        disclaimer_text = st.session_state.payload.get("disclaimer", "")
    if not disclaimer_text:
        disclaimer_text = load_fallback_disclaimer()
    render_disclaimer(disclaimer_text)


if __name__ == "__main__":
    main()
