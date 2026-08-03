"""ASD-GenDecoder 前端：单文件 Streamlit 应用「静谧证据台」。

骨架文件，只定义结构与签名，不含业务实现。属主为前端智能体（见 AGENTS.md 第 1 节）。

函数清单与调用顺序照 docs/UI_BLUEPRINT.md §8，**函数名不得改、不得增删**。
视觉令牌、组件编号（C-xx）与验收清单同见该文档。

启动：streamlit run app.py（需后端 uvicorn 进程同时运行）
"""

import json
import re
from functools import lru_cache
from html import escape

import requests
import streamlit as st

from config import BACKEND_URL, FIXTURES_DIR, official_disclaimer

# ---------- 常量与工具 ----------

# 后端未就绪时置 True，改读 data/fixtures/ 下的 mock，可跑通全部渲染分区。
USE_MOCK: bool = False

# 比对卡页脚的引用编号（§5.3）
CIRCLED = "①②③④⑤⑥⑦⑧⑨"

# docs/UI_BLUEPRINT.md §7 全文，通过 st.markdown(unsafe_allow_html=True) 注入。
CSS: str = """
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

/* 全局 */
html, body, [class*="css"]{ font-family:var(--font-sans); color:var(--text-primary); }
.stApp{ background:var(--bg-canvas); }
.block-container{ max-width:1180px; padding:32px 32px 64px; }
#MainMenu, footer{ visibility:hidden; }

/* C-01 */
.ced-header{ border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:24px; }
.ced-title{ font-size:24px; line-height:1.4; font-weight:600; }
.ced-sub{ font-size:16px; line-height:1.8; color:var(--text-muted); margin-top:4px; }

/* 通用分区 */
.ced-section{ margin-bottom:32px; }
.ced-section-title{ font-size:18px; line-height:1.5; font-weight:600; margin-bottom:12px; }
.ced-note{ font-size:13px; line-height:1.6; color:var(--text-muted-strong); }
.ced-card{ background:var(--bg-surface); border:1px solid var(--border);
           border-radius:var(--radius); box-shadow:var(--shadow); padding:20px; margin-bottom:16px; }
.ced-idle{ text-align:center; padding:48px 24px; }
.ced-loading{ background:var(--bg-panel); border-radius:var(--radius); padding:20px; margin-bottom:32px; }
.ced-loading .ced-note{ margin-top:8px; }
.ced-warning{ color:var(--bucket-c); font-size:13px; line-height:1.6; }
.ced-confidence{ margin-top:16px; font-size:13px; line-height:1.6; color:var(--text-muted-strong); }
.ced-confidence span{ font-family:var(--font-mono); }

/* C-05 */
.ced-quote{ border-left:3px solid var(--bucket-b); padding-left:16px;
            font-size:17px; line-height:1.9; }

/* C-06 */
.ced-hpo{ width:100%; border-collapse:collapse; }
.ced-hpo th{ text-align:left; font-size:13px; font-weight:400; color:var(--text-muted-strong);
             padding:0 0 8px; border-bottom:1px solid var(--border); }
.ced-hpo td{ padding:12px 0; border-bottom:1px solid var(--border);
             font-size:16px; line-height:1.8; vertical-align:top; }
.ced-hpo tr:last-child td{ border-bottom:none; }
.ced-hpo .ced-std{ font-weight:600; }
.ced-hpoid{ font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); margin-left:8px; }

/* C-07 */
.ced-cmp-head{ display:flex; align-items:center; gap:8px; margin-bottom:12px; }
.ced-cmp-title{ font-size:18px; font-weight:600; }
.ced-gene{ font-family:var(--font-mono); font-size:13px; background:var(--brand-soft);
           color:var(--brand-strong); border-radius:999px; padding:2px 10px; }
.ced-anchors{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
.ced-anchor{ font-size:13px; background:var(--brand-soft); color:var(--brand-strong);
             border-radius:999px; padding:2px 10px; }
.ced-cmp-body{ font-size:16px; line-height:1.8; }
.ced-cmp-src{ margin-top:12px; padding-top:12px; border-top:1px solid var(--border);
              text-align:right; font-family:var(--font-mono); font-size:13px; color:var(--text-muted-strong); }
.ced-cmp-note{ margin-bottom:12px; }

/* C-08 */
.ced-step{ display:flex; gap:12px; margin-bottom:12px; }
.ced-step-idx{ flex:0 0 20px; height:20px; margin-top:4px; border-radius:4px;
               background:var(--brand-soft); color:var(--brand-strong);
               font-size:13px; text-align:center; line-height:20px; }
.ced-step-txt{ font-size:16px; line-height:1.8; }

/* C-09 / C-10 右栏 */
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

/* C-11 / C-12 */
.ced-disclaimer{ background:var(--bucket-c-soft); border-left:4px solid var(--bucket-c);
                 border-radius:var(--radius); padding:20px; margin-top:32px; }
.ced-disclaimer-label{ font-size:13px; font-weight:600; color:var(--bucket-c); margin-bottom:8px; }
.ced-disclaimer-body{ font-size:16px; line-height:1.8; }
.ced-error{ background:var(--bucket-c-soft); border:1px solid var(--bucket-c);
            border-radius:var(--radius); padding:20px; }
.ced-error-title{ font-size:18px; font-weight:600; color:var(--bucket-c); margin-bottom:8px; }

/* Streamlit 控件覆盖 */
.stButton>button, .stFormSubmitButton>button{
  background:var(--brand); color:#fff; border:none; border-radius:var(--radius);
  font-weight:600; padding:10px 20px; }
.stButton>button:hover, .stFormSubmitButton>button:hover{ background:var(--brand-strong); color:#fff; }
.st-key-retry button{ background:var(--bg-surface); color:var(--brand-strong);
  border:1px solid var(--border); }
.st-key-retry button:hover{ background:var(--brand-soft); color:var(--brand-strong);
  border:1px solid var(--brand); }
.stTextArea textarea{ background:var(--bg-surface); border:1px solid var(--border);
  border-radius:var(--radius); font-size:16px; line-height:1.8; color:var(--text-primary); }
.stTextArea textarea:focus{ border-color:var(--brand); box-shadow:none; }
.st-key-gene_report textarea{ font-family:var(--font-mono); }
div[data-baseweb="notification"]{ background:var(--bucket-c-soft) !important;
  border-left:4px solid var(--bucket-c) !important; color:var(--text-primary) !important; }
"""


@lru_cache(maxsize=1)
def load_fallback_disclaimer() -> str:
    """非成功态没有响应体时的免责声明来源。

    读 data/knowledge/bucket_c_compliance.json 中 is_disclaimer == true 的 text，
    启动时读一次缓存。**禁止在本文件里硬编码该段文字**（验收项 V2）。
    读取失败时返回空字符串，并由 render_disclaimer 渲染一行读取失败提示——
    绝不静默隐藏免责条。
    """
    try:
        return official_disclaimer()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return ""


def load_mock(kind: str) -> dict:
    """读取 data/fixtures/mock_response.{success,error}.json。kind in {"success", "error"}。"""
    if kind not in {"success", "error"}:
        raise ValueError("kind 必须为 success 或 error")

    payload = json.loads(
        (FIXTURES_DIR / f"mock_response.{kind}.json").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise ValueError("Mock 响应必须是 JSON 对象")
    return payload


def call_backend(symptoms: str, gene_report: str) -> tuple[str, dict]:
    """POST 到 {BACKEND_URL}/api/screen，返回 (stage, payload_or_err)。

    stage in {"success", "error"}。请求与 JSON 解析全程 try/except：
    连接失败、超时、非 200、响应无法解析都必须落到 error 分支，
    进程不崩溃、不白屏、不把 traceback 打到页面（AC6 / 验收项 S3、V5）。
    """
    try:
        if USE_MOCK:
            payload = load_mock("success")
        else:
            response = requests.post(
                f"{BACKEND_URL}/api/screen",
                json={"symptoms": symptoms, "gene_report": gene_report},
                timeout=120,
            )
            try:
                payload = response.json()
            except requests.exceptions.JSONDecodeError:
                payload = {}

            if response.status_code != 200:
                if not isinstance(payload, dict):
                    payload = {}
                return "error", {
                    "error_code": payload.get("error_code", "HTTP_ERROR"),
                    "error_message": payload.get(
                        "error_message",
                        f"后端服务返回 HTTP {response.status_code}，请稍后重试。",
                    ),
                }

        if not isinstance(payload, dict) or payload.get("status") != "success":
            return "error", {
                "error_code": "INVALID_RESPONSE",
                "error_message": "后端返回了无法识别的响应。",
            }
        return "success", payload
    except requests.Timeout:
        return "error", {
            "error_code": "CONNECTION_ERROR",
            "error_message": "连接后端服务超时，请稍后重试。",
        }
    except requests.ConnectionError:
        return "error", {
            "error_code": "CONNECTION_ERROR",
            "error_message": "无法连接后端服务，请确认后端已启动。",
        }
    except (OSError, ValueError, requests.RequestException):
        return "error", {
            "error_code": "REQUEST_ERROR",
            "error_message": "请求处理失败，请稍后重试。",
        }


def match_chunk_refs(comparisons: list, chunks: list) -> list:
    """为每张比对卡算出它引用了右栏哪几条切片，返回下标列表的列表。算法见 §5.2。"""
    generic_tokens = {
        "genereviews",
        "pubmed",
        "aap",
        "acmg",
        "fda",
        "curated",
        "related",
        "disorders",
        "disorder",
        "syndrome",
        "review",
        "reviews",
        "the",
        "of",
        "and",
        "a",
        "an",
    }

    def tokenize(value) -> set[str]:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
        return set(normalized.split())

    def score(comparison: dict, chunk: dict) -> int:
        chunk_tokens = tokenize(chunk.get("source", ""))
        comparison_tokens = tokenize(comparison.get("source", ""))
        gene_tokens = tokenize(comparison.get("gene", ""))

        value = 0
        if gene_tokens and gene_tokens.issubset(chunk_tokens):
            value += 2
        value += len(
            (comparison_tokens - generic_tokens)
            & (chunk_tokens - generic_tokens)
        )
        return value

    matches: list[list[int]] = []
    safe_chunks = [chunk if isinstance(chunk, dict) else {} for chunk in chunks]
    for item in comparisons:
        comparison = item if isinstance(item, dict) else {}
        scores = [score(comparison, chunk) for chunk in safe_chunks]
        best = max(scores, default=0)
        if best == 0:
            matches.append([])
            continue
        matches.append(
            [index for index, value in enumerate(scores) if value == best][:2]
        )
    return matches


# ---------- 渲染函数（每个内部只做一次 st.markdown） ----------


def render_header() -> None:
    """页眉。"""
    st.markdown(
        """
        <div class="ced-header">
          <div class="ced-title">ASD-GenDecoder · 就诊前置信息整理</div>
          <div class="ced-sub">帮你把孩子的表现和基因报告，翻译成可以带去门诊的语言</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_idle_hint() -> None:
    """C-13 空闲态提示。"""
    st.markdown(
        """
        <div class="ced-idle">
          <div class="ced-section-title">填写下方两个输入框，生成可带去门诊的信息整理单</div>
          <div class="ced-note">
            把白话症状对应到 HPO 标准术语<br>
            与文献中的鉴别锚点做客观比对<br>
            整理出就诊时该带什么、该说什么
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_loading() -> None:
    """C-14 加载态。"""
    st.markdown(
        """
        <div class="ced-loading">
          <div class="ced-section-title">正在生成…</div>
          <div class="ced-note">
            术语标准化 (MCP)<br>
            知识检索 (RAG)<br>
            报告合成 (M3)
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_reassurance(text: str) -> None:
    """C-05 VUS 降焦虑话术。"""
    if not text:
        return
    safe_text = escape(str(text)).replace("\n", "<br>")
    st.markdown(
        (
            '<section class="ced-section">'
            '<div class="ced-section-title">关于「临床意义未明」，先看这段</div>'
            f'<div class="ced-quote">{safe_text}</div>'
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_hpo_table(hpo_terms: list) -> None:
    """C-06 表型标准化对照表。hpo_id 用等宽字体。"""
    rows = []
    for item in hpo_terms if isinstance(hpo_terms, list) else []:
        term = item if isinstance(item, dict) else {}
        matched_text = escape(str(term.get("matched_text") or "—"))
        name = escape(str(term.get("name") or "—"))
        hpo_id = escape(str(term.get("hpo_id") or ""))
        hpo_markup = f'<span class="ced-hpoid">{hpo_id}</span>' if hpo_id else ""
        rows.append(
            "<tr>"
            f"<td>「{matched_text}」</td>"
            f'<td><span class="ced-std">{name}</span>{hpo_markup}</td>'
            "</tr>"
        )

    if rows:
        content = (
            '<table class="ced-hpo">'
            "<colgroup><col style=\"width:58%\"><col style=\"width:42%\"></colgroup>"
            "<thead><tr><th>家长原话</th><th>HPO 标准术语</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    else:
        content = '<div class="ced-note">本次未能标准化出表型术语</div>'

    st.markdown(
        (
            '<section class="ced-section">'
            '<div class="ced-section-title">您的描述 → 医学术语</div>'
            f"{content}"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_comparisons(comparisons: list, refs: list) -> None:
    """C-07 逐病比对卡；comparisons 为空数组时渲染 C-16 静默态。

    静默态下**不得出现任何推测性病名**（验收项 V3）。页脚用 CIRCLED 标注引用编号。
    """
    safe_comparisons = comparisons if isinstance(comparisons, list) else []
    if not safe_comparisons:
        markup = """
            <section class="ced-section">
              <div class="ced-section-title">本次未匹配到相关指南条目。</div>
              <div class="ced-note">
                这不代表存在问题，也不代表可以排除问题，只说明知识库里没有可比对的文献特征。请以医生面诊为准。
              </div>
            </section>
            """
    else:
        cards = []
        safe_refs = refs if isinstance(refs, list) else []
        for index, item in enumerate(safe_comparisons):
            comparison = item if isinstance(item, dict) else {}
            explanation = comparison.get("explanation")
            if not explanation:
                continue

            condition = escape(str(comparison.get("condition") or "未命名比对项"))
            gene = escape(str(comparison.get("gene") or ""))
            gene_markup = f'<span class="ced-gene">{gene}</span>' if gene else ""

            anchors = comparison.get("matched_anchors")
            anchor_markup = ""
            if isinstance(anchors, list) and anchors:
                anchor_markup = (
                    '<div class="ced-anchors">'
                    + "".join(
                        f'<span class="ced-anchor">{escape(str(anchor))}</span>'
                        for anchor in anchors
                    )
                    + "</div>"
                )

            source = escape(str(comparison.get("source") or "—"))
            reference_numbers = safe_refs[index] if index < len(safe_refs) else []
            reference_markup = []
            if isinstance(reference_numbers, list):
                for ref_index in reference_numbers:
                    if not isinstance(ref_index, int) or ref_index < 0:
                        continue
                    reference_markup.append(
                        CIRCLED[ref_index]
                        if ref_index < len(CIRCLED)
                        else f"({ref_index + 1})"
                    )
            suffix = f" {' '.join(reference_markup)}" if reference_markup else ""
            safe_explanation = escape(str(explanation)).replace("\n", "<br>")

            cards.append(
                '<article class="ced-card">'
                '<div class="ced-cmp-head">'
                f'<div class="ced-cmp-title">{condition}</div>{gene_markup}'
                "</div>"
                f"{anchor_markup}"
                f'<div class="ced-cmp-body">{safe_explanation}</div>'
                f'<div class="ced-cmp-src">来源：{source}{suffix}</div>'
                "</article>"
            )

        markup = (
            '<section class="ced-section">'
            '<div class="ced-section-title">需请医生一并排除的方向</div>'
            '<div class="ced-note ced-cmp-note">'
            "以下均为文献特征的客观比对，不是结论。"
            "</div>"
            f"{''.join(cards)}"
            "</section>"
        )

    st.markdown(
        markup,
        unsafe_allow_html=True,
    )


def render_next_steps(steps: list) -> None:
    """C-08 就诊建议清单。"""
    safe_steps = steps if isinstance(steps, list) else []
    if safe_steps:
        content = "".join(
            '<div class="ced-step">'
            f'<div class="ced-step-idx">{index}</div>'
            f'<div class="ced-step-txt">{escape(str(step))}</div>'
            "</div>"
            for index, step in enumerate(safe_steps, start=1)
        )
    else:
        content = '<div class="ced-warning">就诊建议缺失</div>'

    st.markdown(
        (
            '<section class="ced-section">'
            '<div class="ced-section-title">下一步就诊清单</div>'
            f"{content}"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_confidence_line(value) -> None:
    """C-17 筛查可信度，PRD C6 Roadmap 字段。

    字段缺失时**静默不渲染**本行。文案只能用「筛查可信度」「匹配可信度」等中性表述，
    禁止「概率」「可能性」「几率」，禁止用颜色梯度暗示数值越高越可能得病（不变量 I9）。
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        return
    st.markdown(
        (
            '<div class="ced-confidence">'
            f"本次筛查可信度：<span>{value} / 100</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_error(err: dict) -> None:
    """C-12 错误卡。任何异常都必须落到这张卡上。"""
    error = err if isinstance(err, dict) else {}
    error_code = str(error.get("error_code") or "")
    title_and_tip = {
        "INVALID_INPUT": ("输入还需要补全", "请检查两个输入框是否都已填写。"),
        "HPO_NO_MATCH": (
            "暂未匹配到标准表型术语",
            "请补充更具体的表现描述，或携带原始记录咨询儿童发育行为科。",
        ),
        "MISSING_API_KEY": (
            "后端缺少模型密钥",
            "请检查项目根目录 .env 中的 MINIMAX_API_KEY。",
        ),
        "MINIMAX_API_ERROR": (
            "模型服务暂时不可用",
            "这通常是限流或超时，稍后重试即可。",
        ),
        "CONNECTION_ERROR": (
            "无法连接后端服务",
            "请确认已执行 uvicorn main:app --reload --port 8000。",
        ),
    }
    title, tip = title_and_tip.get(error_code, ("请求失败", ""))
    message = escape(str(error.get("error_message") or "后端未返回错误详情"))
    tip_markup = f'<div class="ced-note">{escape(tip)}</div>' if tip else ""

    st.markdown(
        (
            '<section class="ced-section">'
            '<div class="ced-error">'
            f'<div class="ced-error-title">{title}</div>'
            f'<div class="ced-cmp-body">{message}</div>'
            f"{tip_markup}"
            "</div>"
            "</section>"
        ),
        unsafe_allow_html=True,
    )

    if st.button("重试", key="retry", type="secondary"):
        st.session_state.stage = "loading"
        st.session_state.payload = None
        st.session_state.err = None
        with st.spinner("正在重新生成…"):
            stage, result = call_backend(
                st.session_state.get("symptoms", ""),
                st.session_state.get("gene_report", ""),
            )
        st.session_state.stage = stage
        st.session_state.payload = result if stage == "success" else None
        st.session_state.err = result if stage == "error" else None
        st.rerun()


def render_intake_form(disabled: bool) -> None:
    """C-03 / C-04 双输入表单与提交按钮。

    两输入框任一为空时 st.warning 拦截并提示补全，**不向后端发请求**（AC8 / 验收项 V6）。
    """
    with st.form(key="intake", clear_on_submit=False):
        st.text_area(
            "孩子的情况",
            height=96,
            key="symptoms",
            placeholder=(
                "孩子3岁，1岁半以前会说的词现在都不说了，最近半年总是不停地搓手绞手，"
                "还经常无缘无故地笑，走路也不太稳。"
            ),
            disabled=disabled,
        )
        st.text_area(
            "基因报告原文",
            height=120,
            key="gene_report",
            placeholder=(
                "全外显子测序（WES）检出 MECP2 基因错义变异 c.455C>G "
                "(p.Pro152Arg)，临床意义未明（VUS）。"
            ),
            disabled=disabled,
        )
        submitted = st.form_submit_button(
            "生成信息整理单",
            type="primary",
            use_container_width=True,
            disabled=disabled,
        )

    if not submitted:
        return
    symptoms = st.session_state.get("symptoms", "")
    gene_report = st.session_state.get("gene_report", "")
    if not str(symptoms).strip() or not str(gene_report).strip():
        st.warning("请同时填写「孩子的情况」与「基因报告原文」后再提交。")
        return

    st.session_state.stage = "loading"
    st.session_state.payload = None
    st.session_state.err = None
    with st.spinner("正在生成信息整理单…"):
        stage, result = call_backend(str(symptoms), str(gene_report))
    st.session_state.stage = stage
    st.session_state.payload = result if stage == "success" else None
    st.session_state.err = result if stage == "error" else None
    st.rerun()


def render_evidence_panel(payload: dict) -> None:
    """C-09 / C-10 / C-15 右栏证据面板：MCP 标准化过程卡 + RAG 命中切片卡。"""
    data = payload if isinstance(payload, dict) else {}
    parts = [
        '<aside class="ced-panel">',
        '<div class="ced-section-title">证据来源</div>',
        '<div class="ced-note ced-cmp-note">左侧每条比对都能在这里找到出处。</div>',
    ]

    if not data or data.get("status") != "success":
        parts.extend(
            [
                '<div class="ced-note">',
                "生成报告后，这里会列出本次引用的全部知识库原文。",
                "</div>",
                "</aside>",
            ]
        )
    else:
        translation = escape(str(data.get("mcp_translation") or "—")).replace(
            "\n", "<br>"
        )
        parts.extend(
            [
                '<article class="ced-chunk">',
                '<div class="ced-section-title">术语标准化过程 (MCP)</div>',
                f'<div class="ced-chunk-text">{translation}</div>',
                "</article>",
            ]
        )

        chunks = data.get("retrieved_chunks")
        safe_chunks = chunks if isinstance(chunks, list) else []
        if not safe_chunks:
            parts.append('<div class="ced-note">本次未检索到知识库切片</div>')

        bucket_labels = {
            "A": ("桶 A · 鉴别锚点", "ced-tag-a"),
            "B": ("桶 B · VUS 科普", "ced-tag-b"),
            "C": ("桶 C · 合规声明", "ced-tag-c"),
        }
        origin_labels = {
            "curated": "精编摘要",
            "genereviews": "GeneReviews 原文",
            "pubmed": "PubMed 原文",
            "aap": "AAP 指南原文",
        }

        for index, item in enumerate(safe_chunks):
            chunk = item if isinstance(item, dict) else {}
            ref_number = (
                CIRCLED[index] if index < len(CIRCLED) else f"({index + 1})"
            )
            bucket = str(chunk.get("bucket") or "")
            bucket_label, bucket_class = bucket_labels.get(
                bucket, ("未知", "ced-origin")
            )
            origin = origin_labels.get(str(chunk.get("origin") or ""))
            origin_markup = (
                f'<span class="ced-origin">{escape(origin)}</span>'
                if origin
                else ""
            )
            source = escape(str(chunk.get("source") or "—"))
            raw_text = str(chunk.get("text") or "—")
            safe_text = escape(raw_text).replace("\n", "<br>")
            if len(raw_text) > 180:
                preview = escape(raw_text[:180]).replace("\n", "<br>")
                text_markup = (
                    f'<div class="ced-chunk-text">{preview}…'
                    "<details><summary>展开原文</summary>"
                    f'<div class="ced-chunk-text">{safe_text}</div>'
                    "</details></div>"
                )
            else:
                text_markup = f'<div class="ced-chunk-text">{safe_text}</div>'

            parts.extend(
                [
                    '<article class="ced-chunk">',
                    '<div class="ced-chunk-head">',
                    f'<span class="ced-refno">{ref_number}</span>',
                    f'<span class="ced-tag {bucket_class}">{bucket_label}</span>',
                    origin_markup,
                    f'<span class="ced-chunk-src">{source}</span>',
                    "</div>",
                    text_markup,
                    "</article>",
                ]
            )

        parts.append("</aside>")

    st.markdown("".join(parts), unsafe_allow_html=True)


def render_disclaimer(text: str) -> None:
    """C-11 合规免责条，固定置底。

    idle / loading / success / error 四种状态下都必须出现，且必须在 st.columns 之外，
    与桶 C 原文逐字一致（验收项 V1）。用琥珀样式，页面不得出现纯红色像素。
    """
    content = text or (
        "无法加载合规声明文本，请检查 data/knowledge/bucket_c_compliance.json"
    )
    safe_content = escape(str(content)).replace("\n", "<br>")
    st.markdown(
        (
            '<section class="ced-disclaimer">'
            '<div class="ced-disclaimer-label">重要声明</div>'
            f'<div class="ced-disclaimer-body">{safe_content}</div>'
            "</section>"
        ),
        unsafe_allow_html=True,
    )


# ---------- 主流程（调用顺序见 §8，不得调整） ----------


def main() -> None:
    st.set_page_config(
        page_title="ASD-GenDecoder",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    state_defaults = {
        "stage": "idle",
        "payload": None,
        "err": None,
        "symptoms": "",
        "gene_report": "",
    }
    for key, default in state_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    stage = st.session_state.stage
    payload = st.session_state.payload
    err = st.session_state.err
    if stage == "success" and (
        not isinstance(payload, dict) or payload.get("status") != "success"
    ):
        stage = "error"
        payload = None
        err = {
            "error_code": "INVALID_RESPONSE",
            "error_message": "后端返回了无法识别的响应。",
        }
    elif stage not in {"idle", "loading", "success", "error"}:
        stage = "error"
        payload = None
        err = {
            "error_code": "INVALID_STATE",
            "error_message": "页面状态异常，请重新提交。",
        }

    render_header()

    left, right = st.columns([62, 38], gap="large")

    with left:
        if stage == "idle":
            render_idle_hint()
        elif stage == "loading":
            render_loading()
        elif stage == "success":
            comparisons = payload.get("comparisons", [])
            chunks = payload.get("retrieved_chunks", [])
            refs = match_chunk_refs(comparisons, chunks)
            render_reassurance(payload.get("vus_reassurance", ""))
            render_hpo_table(payload.get("hpo_terms", []))
            render_comparisons(comparisons, refs)
            render_next_steps(payload.get("next_steps", []))
            render_confidence_line(payload.get("confidence_level"))
        else:
            render_error(err)

        render_intake_form(disabled=stage == "loading")

    with right:
        render_evidence_panel(payload if stage == "success" else {})

    # 必须在 columns 之外，保证任何状态下都置底且横跨整页
    disclaimer = (
        payload.get("disclaimer", "") if stage == "success" else ""
    ) or load_fallback_disclaimer()
    render_disclaimer(disclaimer)


if __name__ == "__main__":
    main()
