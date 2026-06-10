import os
import json
import time
from datetime import datetime

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def get_file_info(path):
    if not os.path.exists(path):
        return None
    stat = os.stat(path)
    return {
        "size": format_size(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    }

base_path = "backend/data/pro_kb"
files_to_check = [
    "pro_kb_cards.jsonl",
    "pro_kb_chunks.jsonl",
    "pro_kb_graph.json",
    "pro_kb_texts.json"
]

results = {}
file_stats = {}

disciplines = set()
chapters = set()
card_count = 0
chunk_count = 0
node_count = 0
edge_count = 0
kp_entity_count = 0

# 1. cards.jsonl
cards_path = os.path.join(base_path, "pro_kb_cards.jsonl")
file_stats["pro_kb_cards.jsonl"] = get_file_info(cards_path)
if os.path.exists(cards_path):
    with open(cards_path, 'r', encoding='utf-8') as f:
        for line in f:
            card = json.loads(line)
            card_count += 1
            if "discipline" in card:
                disciplines.add(card["discipline"])
            if "chapter" in card:
                chapters.add(card["chapter"])

# 2. chunks.jsonl
chunks_path = os.path.join(base_path, "pro_kb_chunks.jsonl")
file_stats["pro_kb_chunks.jsonl"] = get_file_info(chunks_path)
if os.path.exists(chunks_path):
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            chunk = json.loads(line)
            chunk_count += 1
            if "discipline" in chunk:
                disciplines.add(chunk["discipline"])
            if "chapter" in chunk:
                chapters.add(chunk["chapter"])

# 3. graph.json
graph_path = os.path.join(base_path, "pro_kb_graph.json")
file_stats["pro_kb_graph.json"] = get_file_info(graph_path)
if os.path.exists(graph_path):
    with open(graph_path, 'r', encoding='utf-8') as f:
        graph = json.load(f)
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        node_count = len(nodes)
        edge_count = len(edges)
        for node in nodes:
            # 知识点实体数优先用图谱节点数中 type=entity 或 label/category 含“知识点”统计
            ntype = node.get("type", "")
            nname = node.get("name", "")
            if ntype in ["entity", "知识点"] or "知识点" in ntype:
                kp_entity_count += 1

# 4. texts.jsonl (Wait, pro_kb_texts.json or jsonl?)
# Check listing above: pro_kb_texts.json exists.
texts_path = os.path.join(base_path, "pro_kb_texts.json")
file_stats["pro_kb_texts.json"] = get_file_info(texts_path)

# Summary table output
print("="*60)
print(f"{'知识库指标统计汇总':^54}")
print("="*60)
print(f"{'指标项':<20} | {'数值':<20}")
print("-" * 45)
print(f"{'知识卡片数':<20} | {card_count}")
print(f"{'切片数':<20} | {chunk_count}")
print(f"{'学科数':<20} | {len(disciplines)}")
print(f"{'章节数':<20} | {len(chapters)}")
print(f"{'知识点实体数':<20} | {kp_entity_count} (口径: 图谱中 type 为'知识点'或含'知识点'的节点)")
print(f"{'图谱节点数':<20} | {node_count}")
print(f"{'图谱边数':<20} | {edge_count}")
print("\n" + "="*60)
print(f"{'文件详细信息':^54}")
print("="*60)
print(f"{'文件名':<25} | {'大小':<12} | {'最后修改时间':<20}")
print("-" * 65)
for fname in files_to_check:
    info = file_stats.get(fname)
    if info:
        print(f"{fname:<25} | {info['size']:<12} | {info['mtime']:<20}")
    else:
        print(f"{fname:<25} | {'不存在':<12} | {'-'}")
print("="*60)
