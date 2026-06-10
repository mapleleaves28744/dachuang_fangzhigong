#!/usr/bin/env python3
"""
FAISS 构建进度监控器
用于监控 build_faiss_kb.py 的执行进度
"""

import os
import json
import subprocess
import time
from datetime import datetime

def check_build_files():
    """检查FAISS构建的输出文件"""
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(os.path.dirname(backend_dir), 'data')
    
    faiss_index = os.path.join(data_dir, 'pro_kb_faiss.index')
    texts_file = os.path.join(data_dir, 'pro_kb_texts.json')
    
    results = {
        'faiss_index': {
            'exists': os.path.exists(faiss_index),
            'size_mb': os.path.getsize(faiss_index) / (1024*1024) if os.path.exists(faiss_index) else 0
        },
        'texts_file': {
            'exists': os.path.exists(texts_file),
            'size_mb': os.path.getsize(texts_file) / (1024*1024) if os.path.exists(texts_file) else 0
        }
    }
    return results

def monitor_build(update_interval=5):
    """监控构建进度"""
    print("=" * 60)
    print("FAISS 构建进度监控器")
    print("=" * 60)
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 获取初始时间
    start_time = time.time()
    
    print("📊 监控项目:")
    print("  1. FAISS 索引文件生成")
    print("  2. 文本映射文件生成")
    print("  3. 构建过程完成度")
    print()
    
    print("⏳ 正在监控构建过程...")
    print(f"   更新间隔: 每 {update_interval} 秒")
    print()
    
    iteration = 0
    max_wait_time = 1800  # 最多等待30分钟
    
    while time.time() - start_time < max_wait_time:
        iteration += 1
        elapsed = int(time.time() - start_time)
        
        files = check_build_files()
        
        print(f"\r[{datetime.now().strftime('%H:%M:%S')}] 已用时: {elapsed}s", end='')
        
        # 检查文件状态
        if files['faiss_index']['exists']:
            faiss_size = files['faiss_index']['size_mb']
            print(f" | FAISS: {faiss_size:.1f}MB ✅", end='')
        else:
            print(f" | FAISS: 构建中... 🔄", end='')
            
        if files['texts_file']['exists']:
            texts_size = files['texts_file']['size_mb']
            print(f" | 文本: {texts_size:.1f}MB ✅", end='')
        else:
            print(f" | 文本: 构建中... 🔄", end='')
        
        # 检查是否构建完成
        if files['faiss_index']['exists'] and files['texts_file']['exists']:
            print()
            print()
            print("=" * 60)
            print("✨ FAISS 构建完成!")
            print("=" * 60)
            print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"总用时: {elapsed} 秒")
            print()
            print("📊 最终文件信息:")
            print(f"  FAISS 索引: {files['faiss_index']['size_mb']:.1f} MB")
            print(f"  文本映射: {files['texts_file']['size_mb']:.1f} MB")
            print()
            print("✅ 系统已准备就绪，可以运行测试脚本")
            return True
        
        time.sleep(update_interval)
    
    print()
    print("⏱️ 监控超时 (30分钟无法建成)")
    return False

if __name__ == '__main__':
    monitor_build()
