"""把 PRD 的验收标准 AC1-AC8 变成可执行门禁。

用法：
    # 先启动后端
    uvicorn main:app --reload --port 8000
    # 再运行
    python scripts/run_acceptance.py
    python scripts/run_acceptance.py --case tc_01_rett   # 只跑单个用例

全部通过退出码 0，任一失败退出码 1。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BACKEND_URL, TEST_CASE_DIR, official_disclaimer  # noqa: E402

CASE_DIR = TEST_CASE_DIR
ENDPOINT = f"{BACKEND_URL}/api/screen"
# M3 是推理模型，带 RAG 切片的长提示词要先跑一段思维链，单次往返常在 30-90 秒。
# 这是客户端等待时长，不是对响应速度的断言。
TIMEOUT = 180
PLANNED_CASE_COUNT = 11

REQUIRED_CASE_FIELDS = {"id", "title", "note", "input", "expect"}
ALLOWED_CASE_FIELDS = REQUIRED_CASE_FIELDS | {"setup"}
ALLOWED_EXPECT_FIELDS = {
    "http_status",
    "min_hpo_terms",
    "expect_conditions_any",
    "expect_buckets",
    "forbid_conditions_any",
    "require_disclaimer",
    "require_next_steps_departments",
    "banned_words",
    "error_code",
}
LIST_EXPECT_FIELDS = {
    "expect_conditions_any",
    "expect_buckets",
    "forbid_conditions_any",
    "require_next_steps_departments",
    "banned_words",
}
EXPECTED_SETUP_MODES = {
    "tc_09_missing_api_key": "missing_api_key",
    "tc_10_minimax_timeout": "minimax_timeout",
    "tc_11_hpo_no_match": "hpo_no_match",
}
ERROR_STATUS_BY_CODE = {
    "INVALID_INPUT": 422,
    "HPO_NO_MATCH": 422,
    "MISSING_API_KEY": 500,
    "MINIMAX_API_ERROR": 502,
}

REQUIRED_FIELDS = [
    "status", "hpo_terms", "comparisons", "vus_reassurance",
    "next_steps", "disclaimer", "mcp_translation", "retrieved_chunks",
]
BASE_BANNED_WORDS = {"确诊", "患有", "即为", "需服用", "建议用药"}
REQUIRED_DEPARTMENTS = {"儿童发育行为科", "医学遗传科"}
CONFIDENCE_BANNED_WORDS = {"概率", "可能性", "几率"}


class CaseLoadError(ValueError):
    """验收用例文件缺失、损坏或偏离数据字典。"""


def _validate_case(path: Path, case: object) -> dict:
    """校验单个用例的顶层结构、输入、期望与确定性 setup 声明。"""
    if not isinstance(case, dict):
        raise CaseLoadError(f"{path.name}: 顶层必须是 JSON 对象")

    fields = set(case)
    missing = REQUIRED_CASE_FIELDS - fields
    unknown = fields - ALLOWED_CASE_FIELDS
    if missing:
        raise CaseLoadError(f"{path.name}: 缺少顶层字段 {sorted(missing)}")
    if unknown:
        raise CaseLoadError(f"{path.name}: 出现未定义顶层字段 {sorted(unknown)}")

    case_id = case["id"]
    if not isinstance(case_id, str) or not case_id:
        raise CaseLoadError(f"{path.name}: id 必须是非空字符串")
    if case_id != path.stem:
        raise CaseLoadError(
            f"{path.name}: id 应与文件名一致，实际为 {case_id!r}"
        )
    for field in ("title", "note"):
        if not isinstance(case[field], str) or not case[field].strip():
            raise CaseLoadError(f"{path.name}: {field} 必须是非空字符串")

    request = case["input"]
    if not isinstance(request, dict):
        raise CaseLoadError(f"{path.name}: input 必须是 JSON 对象")
    if set(request) != {"symptoms", "gene_report"}:
        raise CaseLoadError(
            f"{path.name}: input 字段必须且只能是 symptoms 与 gene_report"
        )
    if not all(isinstance(request[field], str) for field in request):
        raise CaseLoadError(f"{path.name}: input 两个字段都必须是字符串")

    expect = case["expect"]
    if not isinstance(expect, dict):
        raise CaseLoadError(f"{path.name}: expect 必须是 JSON 对象")
    unknown_expect = set(expect) - ALLOWED_EXPECT_FIELDS
    if unknown_expect:
        raise CaseLoadError(
            f"{path.name}: expect 出现未定义字段 {sorted(unknown_expect)}"
        )
    status = expect.get("http_status")
    if isinstance(status, bool) or not isinstance(status, int):
        raise CaseLoadError(f"{path.name}: expect.http_status 必须是整数")
    for field in LIST_EXPECT_FIELDS:
        if field not in expect:
            continue
        value = expect[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise CaseLoadError(
                f"{path.name}: expect.{field} 必须是非空字符串数组"
            )

    if status == 200:
        minimum = expect.get("min_hpo_terms")
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or minimum < 1
        ):
            raise CaseLoadError(
                f"{path.name}: HTTP 200 用例的 min_hpo_terms 必须是至少 1 的整数"
            )
    elif not isinstance(expect.get("error_code"), str):
        raise CaseLoadError(
            f"{path.name}: 非 200 用例必须声明 expect.error_code"
        )
    elif expect["error_code"] not in ERROR_STATUS_BY_CODE:
        raise CaseLoadError(
            f"{path.name}: 未定义的 expect.error_code "
            f"{expect['error_code']!r}"
        )
    elif ERROR_STATUS_BY_CODE[expect["error_code"]] != status:
        raise CaseLoadError(
            f"{path.name}: {expect['error_code']} 应对应 HTTP "
            f"{ERROR_STATUS_BY_CODE[expect['error_code']]}，实际声明 {status}"
        )

    expected_mode = EXPECTED_SETUP_MODES.get(case_id)
    setup = case.get("setup")
    if expected_mode is None:
        if setup is not None:
            raise CaseLoadError(f"{path.name}: 此用例不应声明 setup")
    elif setup != {"mode": expected_mode}:
        raise CaseLoadError(
            f"{path.name}: setup 必须为 {{'mode': {expected_mode!r}}}"
        )

    return case


def load_cases(case_id: Optional[str] = None) -> list[tuple[Path, dict]]:
    """装载并校验全部 11 个用例，可在校验全集后按 id 筛选单例。"""
    paths = sorted(CASE_DIR.glob("tc_*.json"))
    if len(paths) != PLANNED_CASE_COUNT:
        raise CaseLoadError(
            f"计划用例数量为 {PLANNED_CASE_COUNT}，实际找到 {len(paths)}"
        )

    loaded = []
    seen_ids = set()
    for path in paths:
        try:
            raw_case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CaseLoadError(f"{path.name}: 无法读取合法 JSON：{exc}") from exc
        case = _validate_case(path, raw_case)
        if case["id"] in seen_ids:
            raise CaseLoadError(f"{path.name}: 用例 id 重复：{case['id']}")
        seen_ids.add(case["id"])
        loaded.append((path, case))

    missing_setup_cases = set(EXPECTED_SETUP_MODES) - seen_ids
    if missing_setup_cases:
        raise CaseLoadError(
            f"缺少确定性错误用例 {sorted(missing_setup_cases)}"
        )

    if case_id:
        loaded = [item for item in loaded if item[1]["id"] == case_id]
        if not loaded:
            raise CaseLoadError(f"未找到用例 {case_id}")
    return loaded


def check_success(case, body, failures):
    exp = case["expect"]

    # AC1 + schema：八个必填字段与成功状态。
    for f in REQUIRED_FIELDS:
        if f not in body:
            failures.append(f"AC1 响应缺失字段 `{f}`")
    if failures:
        return
    if body["status"] != "success":
        failures.append(
            f"AC1 成功响应 status 应为 success，实际 {body['status']!r}"
        )

    terms = body["hpo_terms"]
    comparisons = body["comparisons"]
    steps_list = body["next_steps"]
    chunks = body["retrieved_chunks"]
    container_types = (
        ("hpo_terms", terms, list),
        ("comparisons", comparisons, list),
        ("next_steps", steps_list, list),
        ("retrieved_chunks", chunks, list),
        ("vus_reassurance", body["vus_reassurance"], str),
        ("disclaimer", body["disclaimer"], str),
        ("mcp_translation", body["mcp_translation"], str),
    )
    invalid_containers = False
    for field, value, expected_type in container_types:
        if not isinstance(value, expected_type):
            failures.append(
                f"schema 字段 {field} 类型错误：应为 {expected_type.__name__}"
            )
            invalid_containers = True
    if invalid_containers:
        return
    if not all(isinstance(item, dict) for item in terms):
        failures.append("schema hpo_terms 每项必须是对象")
        return
    if not all(isinstance(item, dict) for item in comparisons):
        failures.append("schema comparisons 每项必须是对象")
        return
    if not all(isinstance(item, str) for item in steps_list):
        failures.append("schema next_steps 每项必须是字符串")
        return
    if not all(isinstance(item, dict) for item in chunks):
        failures.append("schema retrieved_chunks 每项必须是对象")
        return

    # schema I4：成功响应必须有足量且格式合法的 HPO。
    if len(terms) < exp.get("min_hpo_terms", 1):
        failures.append(
            f"schema I4 hpo_terms 数量 {len(terms)} 少于要求的 "
            f"{exp.get('min_hpo_terms', 1)}"
        )
    for t in terms:
        if not str(t.get("hpo_id", "")).startswith("HP:"):
            failures.append(
                f"schema I4 hpo_id 格式非法：{t.get('hpo_id')!r}"
            )

    # schema I1：免责声明始终逐字等于桶 C 原文。
    if body["disclaimer"].strip() != official_disclaimer().strip():
        failures.append(
            "schema I1 disclaimer 与桶 C 原文不一致（必须逐字相同）"
        )

    # schema I2：两个交还医生的科室缺一不可。
    steps = " ".join(steps_list)
    required_departments = REQUIRED_DEPARTMENTS | set(
        exp.get("require_next_steps_departments", [])
    )
    for dept in sorted(required_departments):
        if dept not in steps:
            failures.append(f"schema I2 next_steps 缺少就诊科室「{dept}」")

    # schema I3：字面扫描范围不含 disclaimer 与 retrieved_chunks，
    # 因为前者是法定免责原文、后者是知识库原文，本就允许出现「确诊」等词。
    scope = " ".join(
        [str(c.get("explanation", "")) for c in comparisons]
        + [body.get("vus_reassurance", "")]
        + steps_list
    )
    banned_words = BASE_BANNED_WORDS | set(exp.get("banned_words", []))
    for w in sorted(banned_words):
        if w in scope:
            failures.append(f"schema I3 输出出现禁用词「{w}」")

    # schema I5：禁止为阴性对照硬凑病种。
    conds = " ".join(
        f"{c.get('condition', '')} {c.get('gene', '')}"
        for c in comparisons
    )
    wanted = exp.get("expect_conditions_any")
    if wanted and not any(w in conds for w in wanted):
        failures.append(
            f"schema I5 comparisons 未命中期望病种之一 {wanted}，"
            f"实际为「{conds.strip()}」"
        )
    for forbidden in exp.get("forbid_conditions_any", []):
        if forbidden in conds:
            failures.append(
                f"schema I5 comparisons 出现不应牵强关联的病种"
                f"「{forbidden}」"
            )

    # schema I6：检索切片必须覆盖用例声明的数据桶。
    buckets = {str(c.get("bucket", "")) for c in chunks}
    for b in exp.get("expect_buckets", []):
        if b not in buckets:
            failures.append(
                f"schema I6 retrieved_chunks 未覆盖数据桶 {b}"
                f"（实际 {sorted(buckets)}）"
            )

    # schema I8：无比对时必须明确告知未匹配，禁止模型自由补写。
    if not comparisons and "未匹配到" not in body["vus_reassurance"]:
        failures.append(
            "schema I8 comparisons 为空时 vus_reassurance 必须含「未匹配到」"
        )

    # schema I9：字段可缺失；若出现则不能为 null，且必须是 0–100 整数。
    if "confidence_level" in body:
        confidence = body["confidence_level"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, int)
            or not 0 <= confidence <= 100
        ):
            failures.append(
                "schema I9 confidence_level 必须是 0–100 整数且不得为 null"
            )
    confidence_scope = " ".join([body["vus_reassurance"]] + steps_list)
    for word in sorted(CONFIDENCE_BANNED_WORDS):
        if word in confidence_scope:
            failures.append(
                f"schema I9 vus_reassurance/next_steps 出现禁用措辞「{word}」"
            )

    # schema I7 只能人工确认：打印论断与候选切片来源供至少三例签字核对。
    sources = ", ".join(
        str(chunk.get("source") or "—") for chunk in chunks
    ) or "无切片"
    for index, comparison in enumerate(comparisons, start=1):
        print(
            f"[待人工核对 I7] {case['id']} 比对 {index}："
            f"{comparison.get('condition', '未命名')} / "
            f"{comparison.get('gene', '—')}"
        )
        print(f"        论断：{comparison.get('explanation', '')}")
        print(f"        候选切片来源：{sources}")


def check_error(case, body, failures):
    exp = case["expect"]
    required_fields = {"status", "error_code", "error_message"}
    missing = required_fields - set(body)
    extra = set(body) - required_fields
    if missing:
        failures.append(
            f"AC6 ErrorResponse 缺少字段 {sorted(missing)}"
        )
    if extra:
        failures.append(
            f"AC6 ErrorResponse 出现未定义字段 {sorted(extra)}"
        )
    if body.get("status") != "error":
        failures.append(f"AC6 错误响应 status 应为 error，实际 {body.get('status')!r}")
    if exp.get("error_code") and body.get("error_code") != exp["error_code"]:
        failures.append(
            f"AC6 error_code 应为 {exp['error_code']}，实际 {body.get('error_code')!r}"
        )
    if (
        not isinstance(body.get("error_message"), str)
        or not body["error_message"].strip()
    ):
        failures.append("AC6 error_message 为空，前端无法展示错误态")


def _request_with_setup(case):
    """在进程内隔离后端，并按 setup.mode 确定性注入错误。"""
    from contextlib import ExitStack, asynccontextmanager
    from unittest.mock import AsyncMock, Mock, patch

    from fastapi.testclient import TestClient

    import main as backend

    @asynccontextmanager
    async def isolated_lifespan(app):
        app.state.hpo = None
        yield

    mode = case["setup"]["mode"]
    setup_failures = []
    mcp_mock = None
    retrieve_mock = None
    synthesize_mock = None

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                backend.app.router,
                "lifespan_context",
                isolated_lifespan,
            )
        )
        if mode == "missing_api_key":
            stack.enter_context(
                patch.object(backend, "MINIMAX_API_KEY", "", create=True)
            )
            mcp_mock = stack.enter_context(
                patch.object(backend, "mcp_translate_symptoms", AsyncMock())
            )
            retrieve_mock = stack.enter_context(
                patch.object(backend, "retrieve_chunks", Mock())
            )
            synthesize_mock = stack.enter_context(
                patch.object(backend, "synthesize_report", Mock())
            )
        elif mode == "minimax_timeout":
            hpo_terms = [
                backend.HpoTerm(
                    hpo_id="HP:0000750",
                    name="语言发育延迟",
                    matched_text="语言能力出现倒退",
                )
            ]
            chunks = [
                backend.Chunk(
                    bucket="A",
                    origin="curated",
                    source="acceptance_timeout_fixture",
                    text="确定性超时用例的检索占位切片。",
                )
            ]
            stack.enter_context(
                patch.object(
                    backend,
                    "mcp_translate_symptoms",
                    AsyncMock(return_value=(hpo_terms, "验收注入：HPO 命中")),
                )
            )
            retrieve_mock = stack.enter_context(
                patch.object(
                    backend,
                    "retrieve_chunks",
                    Mock(return_value=chunks),
                )
            )
            synthesize_mock = stack.enter_context(
                patch.object(
                    backend,
                    "synthesize_report",
                    Mock(
                        side_effect=backend.ScreeningError(
                            502,
                            "MINIMAX_API_ERROR",
                            "验收注入：MiniMax 请求超时。",
                        )
                    ),
                )
            )
        elif mode == "hpo_no_match":
            stack.enter_context(
                patch.object(
                    backend,
                    "mcp_translate_symptoms",
                    AsyncMock(
                        return_value=([], "验收注入：全部 HPO 关键词无命中")
                    ),
                )
            )
            retrieve_mock = stack.enter_context(
                patch.object(backend, "retrieve_chunks", Mock())
            )
            synthesize_mock = stack.enter_context(
                patch.object(backend, "synthesize_report", Mock())
            )
        else:
            raise CaseLoadError(f"不支持的 setup.mode：{mode}")

        with TestClient(
            backend.app, raise_server_exceptions=False
        ) as client:
            response = client.post("/api/screen", json=case["input"])

    if mode == "missing_api_key":
        if mcp_mock.called:
            setup_failures.append("setup missing_api_key 后仍调用了 MCP")
        if retrieve_mock.called:
            setup_failures.append("setup missing_api_key 后仍调用了 RAG 检索")
        if synthesize_mock.called:
            setup_failures.append("setup missing_api_key 后仍调用了报告合成")
    elif mode == "minimax_timeout":
        if retrieve_mock.call_count != 1:
            setup_failures.append("setup minimax_timeout 未进入 RAG 检索阶段")
        if synthesize_mock.call_count != 1:
            setup_failures.append("setup minimax_timeout 未进入报告合成阶段")
    elif mode == "hpo_no_match":
        if retrieve_mock.called:
            setup_failures.append("setup hpo_no_match 后仍调用了 RAG 检索")
        if synthesize_mock.called:
            setup_failures.append("setup hpo_no_match 后仍调用了报告合成")

    return response, setup_failures


def run_case(path: Path, case=None):
    if case is None:
        case = _validate_case(
            path, json.loads(path.read_text(encoding="utf-8"))
        )
    exp = case["expect"]
    failures = []

    if "setup" in case:
        resp, setup_failures = _request_with_setup(case)
        failures.extend(setup_failures)
    else:
        try:
            resp = requests.post(
                ENDPOINT, json=case["input"], timeout=TIMEOUT
            )
        except requests.exceptions.ConnectionError:
            return case, ["无法连接后端，请先运行 uvicorn main:app --port 8000"]
        except requests.exceptions.Timeout:
            return case, [f"请求超时（>{TIMEOUT}s）"]

    want_status = exp.get("http_status", 200)
    if resp.status_code != want_status:
        failures.append(f"HTTP 状态码应为 {want_status}，实际 {resp.status_code}")

    try:
        body = resp.json()
    except ValueError:
        failures.append("响应体不是合法 JSON")
        return case, failures
    if not isinstance(body, dict):
        failures.append("响应体顶层必须是 JSON 对象")
        return case, failures

    if want_status == 200:
        check_success(case, body, failures)
    else:
        check_error(case, body, failures)

    return case, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="只运行指定用例 id")
    args = parser.parse_args()

    try:
        loaded_cases = load_cases(args.case)
    except CaseLoadError as exc:
        print(f"用例装载失败：{exc}", file=sys.stderr)
        return 1

    print(f"目标后端：{ENDPOINT}")
    print(f"用例数量：{len(loaded_cases)}\n")

    passed = 0
    for path, loaded_case in loaded_cases:
        try:
            case, failures = run_case(path, loaded_case)
        except Exception as exc:
            case = loaded_case
            failures = [
                f"验收执行异常：{type(exc).__name__}: {exc}"
            ]
        if failures:
            print(
                f"[FAIL] {case['id']} — {case['title']}",
                file=sys.stderr,
            )
            for f in failures:
                print(f"        {f}", file=sys.stderr)
        else:
            passed += 1
            print(f"[PASS] {case['id']} — {case['title']}")

    total = len(loaded_cases)
    if passed != total:
        print(
            f"[FAIL] 验收未通过：通过 {passed}/{total}，"
            "PRD AC1-AC8 存在未满足项。",
            file=sys.stderr,
        )
        return 1
    print(f"全部通过：{passed}/{total}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
