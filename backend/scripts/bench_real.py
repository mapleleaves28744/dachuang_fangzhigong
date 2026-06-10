#!/usr/bin/env python3
"""
实际性能基准测试 - 简化版
目标：用真实数据替代虚拟数据
运行：python bench_real.py
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

def load_simple_env_files():
    candidates = [
        os.path.join(BACKEND_DIR, "config", ".env"),
        os.path.join(BACKEND_DIR, ".env"),
        os.path.join(PROJECT_ROOT, ".env"),
    ]
    for env_path in candidates:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and not os.getenv(key):
                        os.environ[key] = value
        except Exception:
            continue

load_simple_env_files()
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

try:
    from app.services.knowledge_base import search_kb
    print("[OK] 知识库模块导入成功")
except ImportError as e:
    print(f"[ERROR] 导入失败: {e}")
    sys.exit(1)


def load_testset(path: str) -> list:
    """加载测试集"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "cases" in data:
            data = data["cases"]
        return [x for x in data if isinstance(x, dict)]
    except Exception as e:
        print(f"[ERROR] 加载测试集失败: {e}")
        return []


def calculate_match_score(hits: list, expected_tags: list) -> float:
    """
    计算匹配度：在前3个结果中，有多少个预期关键词被匹配到
    """
    if not expected_tags:
        return 1.0
    
    hit_text = " ".join([
        str(h.get("title", "")) + " " + str(h.get("snippet", ""))
        for h in hits[:3]
    ]).lower()
    
    matched = 0
    for tag in expected_tags:
        if str(tag).lower() in hit_text:
            matched += 1
    
    return round(matched / max(1, len(expected_tags)), 4)


def run_benchmark(testset_path: str, top_k: int = 3) -> dict:
    """
    运行真实基准测试
    """
    cases = load_testset(testset_path)
    if not cases:
        print("[ERROR] 无有效的测试用例")
        return {}
    
    print(f"\n[RUN] 开始基准测试...")
    print(f"[INFO] 加载了 {len(cases)} 个测试用例\n")
    
    latencies = []
    precisions = []
    errors = []
    
    for i, case in enumerate(cases):
        query = str(case.get("query", "")).strip()
        expected_tags = case.get("expected_tags", [])
        
        if not query:
            print(f"  [WARN] Case {i}: 跳过空查询")
            continue
        
        try:
            # 执行搜索（计时）
            start = time.time()
            result = search_kb(
                user_id="bench_user",
                query=query,
                top_k=max(1, min(10, int(top_k or 3)))
            )
            latency_ms = (time.time() - start) * 1000
            
            # 获取结果
            hits = result.get("hits", []) if result else []
            precision = calculate_match_score(hits, expected_tags)
            
            latencies.append(latency_ms)
            precisions.append(precision)
            
            status = "[OK]" if precision >= 0.5 else "[LOW]"
            print(f"  {status} Case {i+1}: 延迟 {latency_ms:.1f}ms, 精度 {precision:.0%}")
            
        except Exception as e:
            error_msg = f"Case {i}: {str(e)}"
            errors.append(error_msg)
            print(f"  [ERROR] {error_msg}")
    
    # 计算统计
    if latencies:
        hit_at_k = sum(1 for p in precisions if p > 0) / len(precisions)
        stats = {
            "sample_count": len(latencies),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
            "median_latency_ms": sorted(latencies)[len(latencies)//2],
            "min_latency": min(latencies),
            "max_latency": max(latencies),
            "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else 0,
            "avg_precision": round(sum(precisions) / len(precisions), 4) if precisions else 0,
            "hit_at_k": round(hit_at_k, 4),
            "error_count": len(errors)
        }
    else:
        stats = {"error": "No successful queries"}
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Run real benchmark for KB retrieval")
    parser.add_argument("--testset", default=os.path.join(BACKEND_DIR, "scripts", "education_testset.json"), help="测试集文件路径")
    parser.add_argument("--top_k", type=int, default=3, help="检索返回数量")
    parser.add_argument("--output", default=os.path.join(PROJECT_ROOT, "docs", "BENCHMARK_REAL_DATA.json"), help="输出结果文件")
    args = parser.parse_args()

    testset_path = args.testset
    
    print("=" * 60)
    print("[BENCHMARK] FZG 系统性能基准测试")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试集: {testset_path}\n")
    
    if not os.path.exists(testset_path):
        print(f"[ERROR] 测试集不存在: {testset_path}")
        return
    
    # 运行基准测试
    results = run_benchmark(testset_path, top_k=args.top_k)
    
    # 输出结果
    if results:
        print("\n" + "=" * 60)
        print("[RESULT] 性能基准测试结果")
        print("=" * 60)
        for key, value in results.items():
            print(f"{key:.<40} {value}")
        
        # 保存到文件
        output_file = args.output
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "testset": testset_path,
                "results": results
            }, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] 结果已保存: {output_file}")
    else:
        print("\n[ERROR] 测试失败")


if __name__ == "__main__":
    main()
