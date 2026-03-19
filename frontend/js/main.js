// 学习计划模块
document.addEventListener('DOMContentLoaded', function() {
  console.log('页面加载完成，开始初始化学习计划...');
  const API_BASE = window.ApiUtils.getApiBase();
  const parseApiResponse = window.ApiUtils.parseApiResponse;
  const withSuggestion = window.ApiUtils.withSuggestion;
  
  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
  }
  
  // 页面加载时获取计划
  loadPlans();
  loadReviewReminders();

  window.addEventListener('knowledge:updated', function () {
    loadPlans();
    loadReviewReminders();
  });

  if (window.UserContext) {
    window.UserContext.onChange(function () {
      loadPlans();
      loadReviewReminders();
    });
  }
  
  // 绑定添加按钮点击事件
  const addBtn = document.getElementById('add-plan-btn');
  if (addBtn) {
    console.log('找到添加按钮，绑定事件');
    addBtn.addEventListener('click', handleAddPlan);
  } else {
    console.error('❌ 错误：找不到 #add-plan-btn 按钮！');
  }
  
  // 绑定回车键
  const taskInput = document.getElementById('new-plan-task');
  if (taskInput) {
    taskInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        handleAddPlan();
      }
    });
  }
  
  // 动态事件委托（处理打勾和删除）
  const planList = document.getElementById('plan-list');
  if (planList) {
    // 打勾功能
    planList.addEventListener('change', function(e) {
      if (e.target.classList.contains('plan-check')) {
        const planItem = e.target.closest('.plan-item');
        const planId = planItem.dataset.id;
        const isCompleted = e.target.checked;
        
        console.log('切换完成状态:', planId, isCompleted);
        
        // 更新UI
        planItem.classList.toggle('completed', isCompleted);
        
        // 更新后端
        updateTaskStatus(planId, isCompleted);
      }
    });
    
    // 删除功能
    planList.addEventListener('click', function(e) {
      if (e.target.classList.contains('delete-btn')) {
        const planItem = e.target.closest('.plan-item');
        const planId = planItem.dataset.id;
        
        if (confirm('确定要删除这个学习计划吗？')) {
          console.log('删除计划:', planId);
          
          // 删除动画
          planItem.style.opacity = '0';
          planItem.style.transform = 'translateX(20px)';
          
          setTimeout(() => {
            planItem.remove();
            // 更新后端
            deleteTaskBackend(planId);
            
            // 检查是否为空
            if (document.querySelectorAll('.plan-item').length === 0) {
              showEmptyState();
            }
          }, 300);
        }
      }
    });
  } else {
    console.error('❌ 错误：找不到 #plan-list 容器！');
  }
  
  // ========== 核心功能函数 ==========
  
  // 加载计划
  async function loadPlans() {
    console.log('正在从后端加载学习计划...');
    
    try {
      const userId = getUserId();
      const response = await fetch(`${API_BASE}/api/plans?user_id=${userId}`);
      const data = await parseApiResponse(response);
      console.log('后端返回数据:', data);

      renderPlans(data.plans || []);
    } catch (error) {
      console.error('加载计划失败:', error);
      const planList = document.getElementById('plan-list');
      if (planList) {
        planList.innerHTML = `<div style="color:#888;">${withSuggestion('学习计划加载失败', error, '刷新页面或稍后重试')}</div>`;
      }
      showEmptyState();
    }
  }
  
  // 渲染计划列表
  function renderPlans(plans) {
    const planList = document.getElementById('plan-list');
    if (!planList) {
      console.error('找不到 #plan-list 元素');
      return;
    }
    
    if (!plans || plans.length === 0) {
      showEmptyState();
      return;
    }
    
    // 按时间排序
    plans.sort((a, b) => a.time.localeCompare(b.time));
    
    planList.innerHTML = plans.map(plan => `
      <div class="plan-item ${plan.completed ? 'completed' : ''}" data-id="${plan.id}">
        <input type="checkbox" class="plan-check" ${plan.completed ? 'checked' : ''}>
        <div class="plan-content">
          <span class="plan-time">${plan.time}</span>
          <span class="plan-task">${plan.task}</span>
        </div>
        <button class="delete-btn" title="删除计划">×</button>
      </div>
    `).join('');
    
    console.log(`已渲染 ${plans.length} 个计划`);
  }
  
  // 显示空状态
  function showEmptyState() {
    const planList = document.getElementById('plan-list');
    if (planList) {
      planList.innerHTML = `
        <div class="empty-state">
          暂无学习计划<br>
          <small>从下方表单添加你的第一个计划</small>
        </div>
      `;
    }
  }
  
  // 添加计划
  async function handleAddPlan() {
    console.log('点击添加按钮');
    
    const timeInput = document.getElementById('new-plan-time');
    const taskInput = document.getElementById('new-plan-task');
    const addBtn = document.getElementById('add-plan-btn');
    
    if (!timeInput || !taskInput || !addBtn) {
      console.error('找不到输入框或按钮');
      return;
    }
    
    const time = timeInput.value;
    const task = taskInput.value.trim();
    
    console.log('输入的值:', { time, task });
    
    // 验证
    if (!time) {
      alert('请选择时间！');
      timeInput.focus();
      return;
    }
    
    if (!task) {
      alert('请输入学习任务！');
      taskInput.focus();
      return;
    }
    
    // 禁用按钮防止重复点击
    addBtn.disabled = true;
    addBtn.textContent = '添加中...';
    
    try {
      const response = await fetch(`${API_BASE}/api/plans`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          user_id: getUserId(),
          time: time,
          task: task
        })
      });
      
      console.log('后端响应状态:', response.status);
      
      const data = await parseApiResponse(response);
      console.log('后端响应数据:', data);

      // 清空输入
      timeInput.value = '';
      taskInput.value = '';
      taskInput.focus();

      // 重新加载计划
      await loadPlans();

      alert('添加成功！');
    } catch (error) {
      console.error('添加失败:', error);
      alert(withSuggestion('添加失败', error, '检查输入后重试'));
    } finally {
      // 恢复按钮
      addBtn.disabled = false;
      addBtn.textContent = '添加计划';
    }
  }
  
  // 更新任务状态
  async function updateTaskStatus(planId, isCompleted) {
    try {
      const response = await fetch(`${API_BASE}/api/plans/${planId}`, {
        method: 'PUT',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          user_id: getUserId(),
          completed: isCompleted
        })
      });
      
      await parseApiResponse(response);
      console.log('状态更新成功');
    } catch (error) {
      console.error('状态更新失败:', error);
    }
  }
  
  // 删除任务（后端）
  async function deleteTaskBackend(planId) {
    try {
      const response = await fetch(`${API_BASE}/api/plans/${planId}`, {
        method: 'DELETE',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ user_id: getUserId() })
      });

      await parseApiResponse(response);
      console.log('后端删除成功');
    } catch (error) {
      console.error('后端删除失败:', error);
    }
  }

  async function loadReviewReminders() {
    const list = document.getElementById('review-reminder-list');
    if (!list) return;

    try {
      const userId = getUserId();
      const response = await fetch(`${API_BASE}/api/review/reminders?user_id=${userId}`);
      const data = await parseApiResponse(response);

      if (!data.due_items || data.due_items.length === 0) {
        list.innerHTML = '<div style="color:#10b981;">今天没有紧急复习项，继续保持。</div>';
        return;
      }

      list.innerHTML = data.due_items.slice(0, 4).map(item => {
        const pct = Math.round((item.mastery || 0) * 100);
        return `<div style="padding:6px 0; border-bottom:1px dashed #e5e7eb;">${item.concept} · 掌握度 ${pct}%</div>`;
      }).join('');
    } catch (error) {
      console.error('加载复习提醒失败:', error);
      list.textContent = withSuggestion('提醒加载失败', error, '刷新页面或稍后重试');
    }
  }
});