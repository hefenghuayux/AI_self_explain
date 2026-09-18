#!/usr/bin/env python3
"""DeepSeek 缓存基线统计脚本（只读）

步骤 0：统计改造前基线
========================
只读解析 external_call_records.raw_response，按 taskType、模型名和 promptVersion
汇总命中 token、未命中 token、输出 token 与结构重试率。

验收条件：
- 脚本不写数据库。
- 随机抽取若干记录，手工核对 usage 字段与统计结果。

用法：
    python ljg_docs/12-提示词共享前缀/02-DeepSeek缓存基线统计.py

环境变量：
    DATABASE_URL    数据库连接 URL（默认读取 .env 文件）
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 解析 raw_response
# ---------------------------------------------------------------------------


@dataclass
class UsageData:
    """从 DeepSeek API 响应中解析的 usage 数据。"""

    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens: int = 0
    total_tokens: int = 0


def parse_usage(raw_response: str | None) -> UsageData | None:
    """从 raw_response JSON 中提取 usage 字段。

    DeepSeek 返回格式：
        {
          "usage": {
            "prompt_cache_hit_tokens": 123,
            "prompt_cache_miss_tokens": 456,
            "completion_tokens": 789,
            "prompt_tokens": 579,
            "total_tokens": 1368
          }
        }
    """
    if not raw_response or not raw_response.strip():
        return None
    try:
        body = json.loads(raw_response)
    except (json.JSONDecodeError, ValueError):
        return None

    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None

    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    completion = usage.get("completion_tokens")
    prompt = usage.get("prompt_tokens")
    total = usage.get("total_tokens")

    if hit is None and miss is None and completion is None:
        return None

    return UsageData(
        prompt_cache_hit_tokens=int(hit) if hit is not None else 0,
        prompt_cache_miss_tokens=int(miss) if miss is not None else 0,
        completion_tokens=int(completion) if completion is not None else 0,
        prompt_tokens=int(prompt) if prompt is not None else 0,
        total_tokens=int(total) if total is not None else 0,
    )


# ---------------------------------------------------------------------------
# 分组聚合
# ---------------------------------------------------------------------------


@dataclass
class StatsGroup:
    """一组 (taskType, model, promptVersion) 下的汇总。"""

    total_count: int = 0
    usage_count: int = 0  # 成功解析出 usage 的记录数
    hit_tokens: list[int] = field(default_factory=list)
    miss_tokens: list[int] = field(default_factory=list)
    completion_tokens: list[int] = field(default_factory=list)
    invalid_count: int = 0  # validation_status == "INVALID" 的记录数
    hit_request_count: int = 0  # prompt_cache_hit_tokens > 0 的请求数
    no_usage_count: int = 0  # raw_response 存在但解析不出 usage 的记录数
    no_raw_response_count: int = 0  # raw_response 为空的记录数
    transport_errors: int = 0  # transport_status != "SUCCESS" 的记录数


def compute(stats: StatsGroup) -> dict[str, object]:
    """计算汇总指标。"""
    n = stats.usage_count
    total_hit = sum(stats.hit_tokens)
    total_miss = sum(stats.miss_tokens)
    total_input = total_hit + total_miss
    total_output = sum(stats.completion_tokens)
    valid_count = stats.total_count - stats.invalid_count - stats.transport_errors

    return {
        # 样本量
        "total_records": stats.total_count,
        "transport_errors": stats.transport_errors,
        "no_raw_response": stats.no_raw_response_count,
        "no_usage": stats.no_usage_count,
        "usable_records": n,
        # 输入 token
        "total_input_tokens": total_input,
        "total_cache_hit_tokens": total_hit,
        "total_cache_miss_tokens": total_miss,
        "avg_input_tokens": round(total_input / n, 1) if n else None,
        "avg_hit_tokens": round(total_hit / n, 1) if n else None,
        "avg_miss_tokens": round(total_miss / n, 1) if n else None,
        # 缓存命中率
        "cache_hit_rate": (
            round(total_hit / total_input * 100, 2) if total_input else None
        ),
        "hit_request_count": stats.hit_request_count,
        "hit_request_rate": (
            round(stats.hit_request_count / n * 100, 2) if n else None
        ),
        "avg_hit_tokens_when_hit": (
            round(total_hit / stats.hit_request_count, 1)
            if stats.hit_request_count
            else None
        ),
        # 输出 token
        "total_output_tokens": total_output,
        "avg_output_tokens": round(total_output / n, 1) if n else None,
        # 结构重试
        "invalid_count": stats.invalid_count,
        "schema_retry_rate": (
            round(stats.invalid_count / valid_count * 100, 2) if valid_count else None
        ),
    }


# ---------------------------------------------------------------------------
# 数据库查询
# ---------------------------------------------------------------------------


def get_database_url() -> str:
    """获取数据库 URL，优先从环境变量读取，否则回退到 .env 文件。"""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    # 尝试从 .env 文件中读取
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", maxsplit=1)[1]

    print("错误：未找到 DATABASE_URL，请设置环境变量或在 .env 文件中配置。", file=sys.stderr)
    sys.exit(1)


def iter_records(database_url: str) -> Iterator[dict[str, object]]:
    """遍历 external_call_records 表，返回每条记录的关键字段。"""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("错误：需要安装 sqlalchemy 和 pymysql：pip install sqlalchemy pymysql", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(database_url)
    query = text("""
        SELECT
            id,
            call_type,
            model,
            transport_status,
            validation_status,
            request_snapshot,
            raw_response,
            created_at
        FROM external_call_records
        ORDER BY id
    """)

    with engine.connect() as conn:
        rows = conn.execute(query)
        for row in rows:
            snapshot = row.request_snapshot
            raw_response = row.raw_response
            yield {
                "id": row.id,
                "call_type": row.call_type,
                "model": row.model,
                "transport_status": row.transport_status,
                "validation_status": row.validation_status,
                "purpose": (
                    snapshot.get("purpose")
                    if isinstance(snapshot, dict)
                    else None
                ),
                "prompt_version": (
                    snapshot.get("promptVersion")
                    if isinstance(snapshot, dict)
                    else None
                ),
                "raw_response": raw_response,
                "created_at": row.created_at,
            }


def iter_records_sqlite(database_url: str) -> Iterator[dict[str, object]]:
    """SQLite 版本的查询（兼容 SQLite 的 JSON 处理）。"""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("错误：需要安装 sqlalchemy", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(database_url)
    query = text("""
        SELECT
            id,
            call_type,
            model,
            transport_status,
            validation_status,
            request_snapshot,
            raw_response,
            created_at
        FROM external_call_records
        ORDER BY id
    """)

    with engine.connect() as conn:
        rows = conn.execute(query)
        for row in rows:
            snapshot = (
                json.loads(row.request_snapshot)
                if isinstance(row.request_snapshot, str) and row.request_snapshot
                else row.request_snapshot
            )
            yield {
                "id": row.id,
                "call_type": row.call_type,
                "model": row.model,
                "transport_status": row.transport_status,
                "validation_status": row.validation_status,
                "purpose": (
                    snapshot.get("purpose") if isinstance(snapshot, dict) else None
                ),
                "prompt_version": (
                    snapshot.get("promptVersion")
                    if isinstance(snapshot, dict)
                    else None
                ),
                "raw_response": row.raw_response,
                "created_at": row.created_at,
            }


def _resolve_task_type(record: dict[str, object]) -> str:
    """从记录中提取 taskType。

    优先使用 request_snapshot 中的 purpose，回退到 call_type。
    """
    purpose = record.get("purpose")
    if purpose and isinstance(purpose, str):
        return purpose
    call_type = record.get("call_type")
    if call_type and isinstance(call_type, str):
        return call_type
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------


def main() -> None:
    start_time = time.perf_counter()
    database_url = get_database_url()
    is_sqlite = database_url.startswith(("sqlite:///", "sqlite+pysqlite:///"))
    print(f"数据库 URL: {database_url[:database_url.index('@') + 1] if '@' in database_url else 'sqlite'}:****")
    print(f"数据库类型: {'SQLite' if is_sqlite else 'MySQL/其他'}")
    print()

    # 确定迭代函数
    record_iter = iter_records_sqlite if is_sqlite else iter_records

    # 按 (taskType, model, promptVersion) 分组
    groups: dict[tuple[str, str, str], StatsGroup] = defaultdict(StatsGroup)
    total_parsed = 0
    parse_errors = 0
    unparsable_ids: list[int] = []

    for record in record_iter(database_url):
        task_type = _resolve_task_type(record)
        model = str(record.get("model", "UNKNOWN"))
        raw_version = record.get("prompt_version")
        prompt_version = str(raw_version) if raw_version is not None else "UNKNOWN"
        key = (task_type, model, prompt_version)

        stat = groups[key]
        stat.total_count += 1

        transport_status = record.get("transport_status")
        validation_status = record.get("validation_status")
        raw_response = record.get("raw_response")

        if transport_status != "SUCCESS":
            stat.transport_errors += 1
            continue

        if validation_status == "INVALID":
            stat.invalid_count += 1

        if not raw_response:
            stat.no_raw_response_count += 1
            continue

        usage = parse_usage(raw_response)
        if usage is None:
            stat.no_usage_count += 1
            unparsable_ids.append(int(record["id"]))
            parse_errors += 1
            continue

        stat.usage_count += 1
        stat.hit_tokens.append(usage.prompt_cache_hit_tokens)
        stat.miss_tokens.append(usage.prompt_cache_miss_tokens)
        stat.completion_tokens.append(usage.completion_tokens)
        if usage.prompt_cache_hit_tokens > 0:
            stat.hit_request_count += 1
        total_parsed += 1

    elapsed = time.perf_counter() - start_time
    total_records = sum(g.total_count for g in groups.values())
    print(f"扫描完成，耗时 {elapsed:.2f} 秒")
    print(f"记录总数: {total_records}")
    print(f"成功解析 usage: {total_parsed}")
    print(f"无法解析 usage: {parse_errors}")
    if unparsable_ids:
        print(f"无法解析的记录 ID 示例: {unparsable_ids[:10]}"
              f"{'...' if len(unparsable_ids) > 10 else ''}")
    print()

    if total_parsed == 0:
        print("没有可用的 usage 数据，请检查数据库是否包含 DeepSeek 调用记录。")
        sys.exit(0)

    # 输出统计结果
    print("=" * 100)
    print("  缓存基线统计结果")
    print("=" * 100)
    print()
    print("分组: taskType | model | promptVersion")
    print("-" * 100)

    all_results: dict[tuple[str, str, str], dict[str, object]] = {}
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2])):
        task_type, model, prompt_version = key
        stat = groups[key]
        result = compute(stat)
        all_results[key] = result

        print(f"\n  [{task_type}]  model={model}  promptVersion={prompt_version}")
        print(f"    样本量:          {result['total_records']} 条")
        print(f"    传输错误:         {result['transport_errors']}")
        print(f"    无 raw_response:  {result['no_raw_response']}")
        print(f"    无 usage:         {result['no_usage']}")
        print(f"    可分析记录:       {result['usable_records']}")
        print(f"    输入 token 合计:  {result['total_input_tokens']:,}")
        print(f"      缓存命中:       {result['total_cache_hit_tokens']:,}")
        print(f"      缓存未命中:     {result['total_cache_miss_tokens']:,}")
        print(f"    平均输入 token:   {result['avg_input_tokens']}")
        print(f"    平均命中 token:   {result['avg_hit_tokens']}")
        print(f"    平均未命中 token: {result['avg_miss_tokens']}")
        print(f"    缓存 token 命中率: {result['cache_hit_rate']}%")
        if result['hit_request_count'] is not None:
            print(f"    有缓存命中的请求:  {result['hit_request_count']} / {stat.usage_count}"
                  f" ({result['hit_request_rate']}%)")
        if result['avg_hit_tokens_when_hit'] is not None:
            print(f"    命中时平均命中量:  {result['avg_hit_tokens_when_hit']}")
        print(f"    输出 token 合计:  {result['total_output_tokens']:,}")
        print(f"    平均输出 token:   {result['avg_output_tokens']}")
        print(f"    Schema 校验无效:  {result['invalid_count']}")
        print(f"    Schema 重试率:    {result['schema_retry_rate']}%")

    # 汇总（所有分组合计）
    print()
    print("-" * 100)
    print("  全局汇总（所有分组合计）")
    print("-" * 100)

    overall = StatsGroup()
    for stat in groups.values():
        overall.total_count += stat.total_count
        overall.usage_count += stat.usage_count
        overall.hit_tokens.extend(stat.hit_tokens)
        overall.miss_tokens.extend(stat.miss_tokens)
        overall.completion_tokens.extend(stat.completion_tokens)
        overall.invalid_count += stat.invalid_count
        overall.hit_request_count += stat.hit_request_count
        overall.no_usage_count += stat.no_usage_count
        overall.no_raw_response_count += stat.no_raw_response_count
        overall.transport_errors += stat.transport_errors

    overall_result = compute(overall)
    print(f"    总记录数:         {overall_result['total_records']}")
    print(f"    可分析记录:       {overall_result['usable_records']}")
    print(f"    输入 token 合计:  {overall_result['total_input_tokens']:,}")
    print(f"      缓存命中:       {overall_result['total_cache_hit_tokens']:,}")
    print(f"      缓存未命中:     {overall_result['total_cache_miss_tokens']:,}")
    print(f"    缓存 token 命中率: {overall_result['cache_hit_rate']}%")
    print(f"    有缓存命中的请求:  {overall_result['hit_request_count']} / {overall.usage_count}"
          f" ({overall_result['hit_request_rate']}%)")
    print(f"    输出 token 合计:  {overall_result['total_output_tokens']:,}")
    print(f"    Schema 重试率:    {overall_result['schema_retry_rate']}%")

    # ---- 额外指标：一次性例子 token 估算 ----
    print()
    print("-" * 100)
    print("  一次性例子 token 估算（仅 AI_TEACHING / generate_teaching）")
    print("-" * 100)

    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2])):
        task_type = key[0]
        if task_type not in ("AI_TEACHING",):
            continue
        stat = groups[key]
        result = all_results[key]
        n = stat.usage_count
        if n > 0:
            avg_output = result["avg_output_tokens"]
            # 估算：例子占输入 token 的 ~5-15%，取中位 10% 做粗略估计
            avg_input = result["avg_input_tokens"] or 0
            estimated_example_cost = round(avg_input * 0.10, 1)
            print(f"    [{task_type}] 平均输入: {avg_input}, "
                  f"估算例子 token: ~{estimated_example_cost}/请求")

    # 保存到 JSON 文件供结果文档使用
    try:
        output_dir = Path(__file__).resolve().parent
    except NameError:
        output_dir = Path.cwd()
    json_path = output_dir / "baseline_data.json"
    serializable = []
    for (task_type, model, prompt_version), stat in groups.items():
        serializable.append({
            "taskType": task_type,
            "model": model,
            "promptVersion": prompt_version,
            "stats": all_results[(task_type, model, prompt_version)],
        })
    serializable.append({
        "taskType": "__OVERALL__",
        "model": "",
        "promptVersion": "",
        "stats": overall_result,
    })
    json_path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细数据已保存至: {json_path}")


if __name__ == "__main__":
    main()