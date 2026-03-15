import os
import json

DATA_DIR = "data"

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_json(filename, default=None):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(filename, data):
    ensure_data_dir()
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 用户学习计划操作
def get_user_plans(user_id):
    plans = load_json("user_plans.json", {})
    return plans.get(user_id, [])

def set_user_plans(user_id, plan_list):
    plans = load_json("user_plans.json", {})
    plans[user_id] = plan_list
    save_json("user_plans.json", plans)

# 用户知识图谱操作（示例，可扩展）
def get_user_knowledge(user_id):
    return load_json(f"{user_id}_knowledge.json", {"concepts": []})

def set_user_knowledge(user_id, knowledge):
    save_json(f"{user_id}_knowledge.json", knowledge)

# 用户画像操作（示例，可扩展）
def get_user_profile(user_id):
    return load_json(f"{user_id}_profile.json", {})

def set_user_profile(user_id, profile):
    save_json(f"{user_id}_profile.json", profile)
