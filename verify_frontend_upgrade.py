#!/usr/bin/env python3
"""
🔍 前端改造验证脚本

功能：
1. 检查 chat-page.js 是否已更新为新的搜索函数
2. 验证必要的辅助函数是否存在
3. 检查 HTML 是否正确引入脚本
4. 生成改造进度报告

使用: python verify_frontend_upgrade.py
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path


def read_file(filepath):
    """读取文件内容"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {str(e)}"


def check_function_exists(content, func_name):
    """检查函数是否存在"""
    pattern = rf'(?:async\s+)?function\s+{re.escape(func_name)}\s*\('
    return bool(re.search(pattern, content))


def check_variable_exists(content, var_name):
    """检查变量是否存在"""
    pattern = rf'(?:const|let|var)\s+{re.escape(var_name)}\s*='
    return bool(re.search(pattern, content))


def check_call_in_file(content, func_name):
    """检查函数调用是否存在"""
    pattern = rf'{re.escape(func_name)}\s*\('
    return len(re.findall(pattern, content))


def generate_report():
    """生成验证报告"""
    print("\n" + "="*60)
    print("🔍 前端改造验证报告")
    print("="*60 + "\n")
    
    workspace_root = os.path.dirname(os.path.abspath(__file__))
    # 向上寻找项目根目录
    for _ in range(3):
        if os.path.exists(os.path.join(workspace_root, 'fzg')):
            workspace_root = os.path.join(workspace_root, 'fzg')
            break
        workspace_root = os.path.dirname(workspace_root)
    
    frontend_dir = os.path.join(workspace_root, 'frontend')
    chat_page_js = os.path.join(frontend_dir, 'assets', 'js', 'pages', 'chat-page.js')
    chat_html = os.path.join(frontend_dir, 'chat.html')
    
    print(f"📍 项目路径: {workspace_root}")
    print(f"📁 前端目录: {frontend_dir}\n")
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'checks': [],
        'summary': {}
    }
    
    # =========== 检查 1: chat-page.js 是否存在 ===========
    print("[1/7] 检查 chat-page.js 存在性...")
    if os.path.exists(chat_page_js):
        print("✅ chat-page.js 存在")
        results['checks'].append(('chat_page_exists', True))
        chat_page_content = read_file(chat_page_js)
    else:
        print("❌ chat-page.js 不存在")
        results['checks'].append(('chat_page_exists', False))
        return results
    
    # =========== 检查 2: 新的搜索函数 ===========
    print("\n[2/7] 检查新的搜索函数...")
    func_name = 'searchKnowledgeFromInput'
    has_function = check_function_exists(chat_page_content, func_name)
    
    if has_function:
        # 检查是否是新版本（应该有 generateEnhancedSearchResultsHTML 调用）
        if 'generateEnhancedSearchResultsHTML' in chat_page_content:
            print(f"✅ 新版 {func_name}() 已安装")
            results['checks'].append(('new_search_function', True))
        else:
            print(f"⚠️  {func_name}() 存在但可能是旧版本")
            print("   (没有检测到 generateEnhancedSearchResultsHTML 调用)")
            results['checks'].append(('new_search_function', 'partial'))
    else:
        print(f"❌ {func_name}() 不存在")
        results['checks'].append(('new_search_function', False))
    
    # =========== 检查 3: 搜索模式变量 ===========
    print("\n[3/7] 检查搜索模式变量...")
    if check_variable_exists(chat_page_content, 'KB_SEARCH_MODES'):
        print("✅ KB_SEARCH_MODES 已定义")
        results['checks'].append(('search_modes_var', True))
    else:
        print("❌ KB_SEARCH_MODES 未定义")
        print("   💡 提示: 应该在 chat-page.js 顶部添加搜索模式变量")
        results['checks'].append(('search_modes_var', False))
    
    # =========== 检查 4: 辅助函数 ===========
    print("\n[4/7] 检查辅助函数...")
    helper_functions = [
        'generateEnhancedSearchResultsHTML',
        'generateSearchResultItemHTML',
        'escapeHtmlForKB',
        'insertKBResultToInput',
        'switchKBSearchMode'
    ]
    
    helper_results = []
    for helper in helper_functions:
        exist = check_function_exists(chat_page_content, helper)
        status = "✅" if exist else "❌"
        print(f"  {status} {helper}()")
        helper_results.append(exist)
    
    results['checks'].append(('helper_functions', all(helper_results)))
    
    if not all(helper_results):
        print(f"\n  ⚠️  缺少 {len([x for x in helper_results if not x])} 个函数")
        print("  💡 提示: 需要从 kb-search-upgrade.js 复制所有辅助函数")
    
    # =========== 检查 5: chat.html 是否引入脚本 ===========
    print("\n[5/7] 检查 chat.html 脚本引入...")
    if os.path.exists(chat_html):
        chat_html_content = read_file(chat_html)
        if 'kb-search-upgrade.js' in chat_html_content or 'enhanced-kb-search.js' in chat_html_content:
            print("✅ 已引入改进的脚本")
            results['checks'].append(('script_linked', True))
        else:
            print("⚠️  chat.html 中未检测到脚本引入")
            print("   💡 提示: 可选，但推荐在 <head> 中添加:")
            print("           <script src=\"assets/js/kb-search-upgrade.js\"></script>")
            results['checks'].append(('script_linked', False))
    else:
        print("❌ chat.html 不存在")
        results['checks'].append(('script_linked', None))
    
    # =========== 检查 6: 后端 API 返回值 ===========
    print("\n[6/7] 检查后端 API 响应字段...")
    knowledge_base_py = os.path.join(workspace_root, 'backend', 'app', 'services', 'knowledge_base.py')
    
    if os.path.exists(knowledge_base_py):
        kb_content = read_file(knowledge_base_py)
        
        api_fields = ['vector_score', 'lexical_score', 'query_time_ms', 'search_mode']
        field_results = []
        
        for field in api_fields:
            exist = field in kb_content
            status = "✅" if exist else "❌"
            print(f"  {status} {field}")
            field_results.append(exist)
        
        results['checks'].append(('api_fields', all(field_results)))
    else:
        print("❌ knowledge_base.py 不存在")
        results['checks'].append(('api_fields', None))
    
    # =========== 检查 7: 浏览器兼容性 ===========
    print("\n[7/7] 检查浏览器兼容性...")
    modern_js_features = ['const', 'fetch', 'async function', '=>']
    
    feature_check = all(feature in chat_page_content for feature in modern_js_features)
    
    if feature_check:
        print("✅ 使用现代 JavaScript 特性")
        print("   浏览器要求: Chrome 55+, Firefox 52+, Safari 11+")
        results['checks'].append(('modern_js', True))
    else:
        print("⚠️  检测到可能的兼容性问题")
        results['checks'].append(('modern_js', False))
    
    # =========== 生成总结 ===========
    print("\n" + "="*60)
    print("📊 验证总结")
    print("="*60 + "\n")
    
    passed = sum(1 for _, result in results['checks'] if result is True)
    failed = sum(1 for _, result in results['checks'] if result is False)
    partial = sum(1 for _, result in results['checks'] if result == 'partial')
    total = len(results['checks'])
    
    results['summary'] = {
        'total': total,
        'passed': passed,
        'failed': failed,
        'partial': partial,
        'progress_percentage': (passed / total * 100) if total > 0 else 0
    }
    
    print(f"✅ 通过: {passed}/{total}")
    print(f"❌ 失败: {failed}/{total}")
    if partial > 0:
        print(f"⚠️  部分完成: {partial}/{total}")
    
    percentage = results['summary']['progress_percentage']
    print(f"\n进度: {percentage:.0f}%")
    
    # 显示进度条
    bar_length = 40
    filled = int(bar_length * percentage / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    print(f"[{bar}]\n")
    
    # =========== 输出建议 ===========
    if failed > 0 or (failed + partial) > 2:
        print("🔧 建议的改造步骤:\n")
        
        checked_items = {name: result for name, result in results['checks']}
        
        if not checked_items.get('new_search_function'):
            print("1. ⚙️  更新 searchKnowledgeFromInput() 函数")
            print("   位置: chat-page.js (第 939 行附近)")
            print("   参考: kb-search-upgrade.js\n")
        
        if not checked_items.get('search_modes_var'):
            print("2. ⚙️  添加搜索模式变量")
            print("   位置: chat-page.js (顶部)")
            print("   变量: KB_SEARCH_MODES, currentKbSearchMode\n")
        
        missing_helpers = [name for name, result in 
                          zip(helper_functions, helper_results) if not result]
        if missing_helpers:
            print(f"3. ⚙️  添加缺失的辅助函数 ({len(missing_helpers)} 个)")
            for helper in missing_helpers:
                print(f"   - {helper}()")
            print()
        
        if not checked_items.get('script_linked'):
            print("4. ⚙️  （可选）在 chat.html 引入脚本")
            print("   位置: <head> 或文件末尾")
            print("   代码: <script src=\"assets/js/kb-search-upgrade.js\"></script>\n")
    
    if failed == 0 and partial == 0:
        print("🎉 太棒了！前端改造已完成！\n")
        print("✨ 现在可以进行以下测试:")
        print("  1. 打开 chat.html")
        print("  2. 输入查询词（例如: '函数求导'）")
        print("  3. 点击'检索知识库'")
        print("  4. 应该看到详细的分数、分类和响应时间\n")
    
    return results


def save_report(results):
    """保存验证报告为 JSON"""
    report_file = 'frontend_upgrade_report.json'
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"📄 报告已保存到: {report_file}\n")
    except Exception as e:
        print(f"⚠️  无法保存报告: {e}\n")


if __name__ == '__main__':
    results = generate_report()
    save_report(results)
    
    print("="*60)
    print("✅ 验证完成！")
    print("="*60)
