(function () {
  const API_BASE = 'http://127.0.0.1:5000';
  const parseApiResponse = window.ApiUtils.parseApiResponse;
  const withSuggestion = window.ApiUtils.withSuggestion;

  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
  }

  const dom = {
    graph: document.getElementById('graph'),
    graphMeta: document.getElementById('graphMeta'),
    nodeTag: document.getElementById('nodeTag'),
    nodeName: document.getElementById('nodeName'),
    nodeDesc: document.getElementById('nodeDesc'),
    nodeDifficulty: document.getElementById('nodeDifficulty'),
    nodeMastery: document.getElementById('nodeMastery'),
    masteryRange: document.getElementById('masteryRange'),
    saveMasteryBtn: document.getElementById('saveMasteryBtn'),
    deleteNodeBtn: document.getElementById('deleteNodeBtn'),
    targetSelect: document.getElementById('targetSelect'),
    fetchPathBtn: document.getElementById('fetchPathBtn'),
    pathList: document.getElementById('pathList'),
    statsChips: document.getElementById('statsChips'),
    mapUserLabel: document.getElementById('mapUserLabel'),
    extractText: document.getElementById('extractText'),
    extractBtn: document.getElementById('extractBtn'),
    extractResult: document.getElementById('extractResult'),
    dueReminderList: document.getElementById('dueReminderList'),
    relationScoreRange: document.getElementById('relationScoreRange'),
    relationScoreText: document.getElementById('relationScoreText')
  };

  const state = {
    chart: null,
    graph: { nodes: [], links: [] },
    selectedNode: null,
    relationScoreThreshold: 0.45
  };

  function refreshRelationScoreText() {
    if (dom.relationScoreText) {
      dom.relationScoreText.textContent = `当前阈值：${Math.round(state.relationScoreThreshold * 100)}%`;
    }
  }

  function masteryToColor(mastery) {
    if (mastery >= 0.8) return '#15803d';
    if (mastery >= 0.6) return '#16a34a';
    if (mastery >= 0.4) return '#ca8a04';
    return '#dc2626';
  }

  function masteryToLabel(mastery) {
    const pct = Math.round(mastery * 100);
    if (mastery >= 0.8) return `${pct}% (熟练)`;
    if (mastery >= 0.6) return `${pct}% (良好)`;
    if (mastery >= 0.4) return `${pct}% (待巩固)`;
    return `${pct}% (薄弱)`;
  }

  function setSelectedNode(node) {
    state.selectedNode = node;
    dom.nodeTag.textContent = '已选择节点';
    dom.nodeName.textContent = node.name;
    dom.nodeDesc.textContent = node.description || '-';
    dom.nodeDifficulty.textContent = (node.difficulty * 100).toFixed(0) + '%';
    dom.nodeMastery.textContent = masteryToLabel(node.mastery);
    dom.masteryRange.value = Math.round(node.mastery * 100);
  }

  function clearSelectedNode() {
    state.selectedNode = null;
    dom.nodeTag.textContent = '未选择节点';
    dom.nodeName.textContent = '-';
    dom.nodeDesc.textContent = '-';
    dom.nodeDifficulty.textContent = '-';
    dom.nodeMastery.textContent = '-';
    dom.masteryRange.value = 30;
  }

  function renderStats(nodes, links) {
    const avg = nodes.length
      ? (nodes.reduce((sum, n) => sum + n.mastery, 0) / nodes.length)
      : 0;
    const weak = nodes.filter(n => n.mastery < 0.4).length;
    const solid = nodes.filter(n => n.mastery >= 0.8).length;

    dom.statsChips.innerHTML = [
      `节点数: ${nodes.length}`,
      `关系数: ${links.length}`,
      `平均掌握度: ${Math.round(avg * 100)}%`,
      `薄弱点: ${weak}`,
      `熟练点: ${solid}`
    ].map(t => `<span class="chip">${t}</span>`).join('');
  }

  function renderTargetSelect(nodes) {
    dom.targetSelect.innerHTML = nodes
      .map(n => `<option value="${n.name}">${n.name}</option>`)
      .join('');
  }

  function renderGraph(nodes, links) {
    if (!state.chart) {
      state.chart = echarts.init(dom.graph);
      window.addEventListener('resize', () => state.chart.resize());
    }

    const option = {
      tooltip: {
        trigger: 'item',
        formatter: (params) => {
          if (params.dataType === 'node') {
            const d = params.data;
            return [
              `<strong>${d.name}</strong>`,
              `掌握度: ${Math.round((d.mastery || 0) * 100)}%`,
              `难度: ${Math.round((d.difficulty || 0) * 100)}%`,
              `描述: ${d.description || '-'}`
            ].join('<br>');
          }
          return `${params.data.source} → ${params.data.target}`;
        }
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          animationDuration: 600,
          force: {
            repulsion: 450,
            edgeLength: [80, 180],
            gravity: 0.08
          },
          label: {
            show: true,
            position: 'right',
            color: '#111827',
            fontSize: 13
          },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: 8,
          lineStyle: {
            color: '#94a3b8',
            opacity: 0.8,
            width: 1.5,
            curveness: 0.1
          },
          emphasis: {
            focus: 'adjacency',
            lineStyle: { width: 2 }
          },
          data: nodes.map(n => ({
            ...n,
            symbolSize: 26 + Math.round((n.mastery || 0) * 28),
            itemStyle: {
              color: masteryToColor(n.mastery || 0),
              borderWidth: 2,
              borderColor: '#ffffff'
            }
          })),
          links
        }
      ]
    };

    state.chart.setOption(option);

    state.chart.off('click');
    state.chart.on('click', (params) => {
      if (params.dataType === 'node') {
        setSelectedNode(params.data);
      }
    });
  }

  async function loadGraph() {
    dom.graphMeta.textContent = '载入中...';
    try {
      const threshold = Number.isFinite(state.relationScoreThreshold) ? state.relationScoreThreshold : 0.45;
      const resp = await fetch(`${API_BASE}/api/knowledge_graph?user_id=${getUserId()}&min_relation_score=${encodeURIComponent(threshold.toFixed(2))}`);
      const data = await parseApiResponse(resp);

      state.graph = data.graph;
      renderGraph(state.graph.nodes, state.graph.links);
      renderTargetSelect(state.graph.nodes);
      renderStats(state.graph.nodes, state.graph.links);

      if (state.graph.nodes.length > 0) {
        setSelectedNode(state.graph.nodes[0]);
      } else {
        clearSelectedNode();
      }

      dom.graphMeta.textContent = `节点 ${data.node_count} · 关系 ${data.edge_count} · 阈值 ${Math.round((data.min_relation_score ?? threshold) * 100)}% · 已更新`;
    } catch (err) {
      dom.graphMeta.textContent = '加载失败';
      dom.pathList.textContent = withSuggestion('图谱数据加载失败', err, '确认后端已启动并刷新页面');
      console.error(err);
    }
  }

  async function saveMastery() {
    if (!state.selectedNode) {
      alert('请先在图谱中选择一个知识点。');
      return;
    }

    const mastery = Number(dom.masteryRange.value) / 100;

    const payload = {
      user_id: getUserId(),
      concept: state.selectedNode.name,
      mastery
    };

    try {
      const resp = await fetch(`${API_BASE}/api/knowledge_graph/mastery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      await parseApiResponse(resp);
      await loadGraph();
      await loadDueReminders();
      window.dispatchEvent(new Event('knowledge:updated'));
    } catch (err) {
      alert(withSuggestion('掌握度保存失败', err, '稍后重试或检查后端服务'));
      console.error(err);
    }
  }

  async function deleteSelectedNode() {
    if (!state.selectedNode) {
      alert('请先在图谱中选择一个知识点。');
      return;
    }

    const concept = state.selectedNode.name;
    const ok = window.confirm(`确认删除知识点「${concept}」吗？该节点关联关系也会被移除。`);
    if (!ok) return;

    try {
      const resp = await fetch(`${API_BASE}/api/knowledge_graph/node`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          concept
        })
      });
      await parseApiResponse(resp);

      await loadGraph();
      await loadDueReminders();
      window.dispatchEvent(new Event('knowledge:updated'));
    } catch (err) {
      alert(withSuggestion('删除节点失败', err, '稍后重试或检查节点状态'));
      console.error(err);
    }
  }

  async function fetchPath() {
    const target = dom.targetSelect.value;
    if (!target) {
      dom.pathList.textContent = '请选择目标知识点';
      return;
    }

    dom.pathList.textContent = '路径计算中...';

    try {
      const resp = await fetch(`${API_BASE}/api/knowledge_graph/path?user_id=${getUserId()}&target=${encodeURIComponent(target)}`);
      const data = await parseApiResponse(resp);

      if (!Array.isArray(data.path) || data.path.length === 0) {
        dom.pathList.textContent = `未找到到达 ${target} 的可行路径，请先补齐前置知识。`;
        return;
      }

      dom.pathList.innerHTML = data.path
        .map((step, idx) => `${idx + 1}. ${step}`)
        .join('<br>');
    } catch (err) {
      dom.pathList.textContent = withSuggestion('路径获取失败', err, '确认目标知识点存在后重试');
      console.error(err);
    }
  }

  async function extractFromText() {
    const text = (dom.extractText.value || '').trim();
    if (!text) {
      dom.extractResult.textContent = '请先输入要抽取的文本。';
      return;
    }

    dom.extractResult.textContent = '抽取中...';
    try {
      const resp = await fetch(`${API_BASE}/api/knowledge_graph/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          text,
          source: 'manual_text'
        })
      });

      const data = await parseApiResponse(resp);

      const concepts = (data.detected_concepts || []).join('、') || '无';
      const rels = (data.relations || []).map(r => `${r.source} -> ${r.target}`).join('；') || '无';
      dom.extractResult.innerHTML = `识别知识点：${concepts}<br>新增关系：${rels}`;

      await loadGraph();
      await loadDueReminders();
      window.dispatchEvent(new Event('knowledge:updated'));
    } catch (err) {
      dom.extractResult.textContent = withSuggestion('抽取失败', err, '缩短文本或稍后重试');
      console.error(err);
    }
  }

  async function loadDueReminders() {
    if (!dom.dueReminderList) return;
    dom.dueReminderList.textContent = '加载中...';

    try {
      const resp = await fetch(`${API_BASE}/api/review/reminders?user_id=${getUserId()}`);
      const data = await parseApiResponse(resp);

      if (!data.due_items || data.due_items.length === 0) {
        dom.dueReminderList.innerHTML = '<span style="color:#10b981;">暂无到期复习项</span>';
        return;
      }

      dom.dueReminderList.innerHTML = data.due_items.slice(0, 4).map(item => {
        const pct = Math.round((item.mastery || 0) * 100);
        return `<div style="padding:4px 0; border-bottom:1px dashed #e2e8f0;">${item.concept} · 掌握度 ${pct}%</div>`;
      }).join('');
    } catch (err) {
      dom.dueReminderList.textContent = withSuggestion('复习提醒加载失败', err, '刷新页面或稍后重试');
      console.error(err);
    }
  }

  function refreshUserLabel() {
    if (dom.mapUserLabel) {
      dom.mapUserLabel.textContent = `当前用户：${getUserId()}`;
    }
  }

  dom.saveMasteryBtn.addEventListener('click', saveMastery);
  if (dom.deleteNodeBtn) {
    dom.deleteNodeBtn.addEventListener('click', deleteSelectedNode);
  }
  dom.fetchPathBtn.addEventListener('click', fetchPath);
  if (dom.extractBtn) {
    dom.extractBtn.addEventListener('click', extractFromText);
  }

  dom.masteryRange.addEventListener('input', function () {
    const value = Number(this.value) / 100;
    dom.nodeMastery.textContent = masteryToLabel(value);
  });

  if (dom.relationScoreRange) {
    dom.relationScoreRange.addEventListener('input', function () {
      const v = Number(this.value) / 100;
      state.relationScoreThreshold = Math.max(0, Math.min(1, v));
      refreshRelationScoreText();
    });

    dom.relationScoreRange.addEventListener('change', function () {
      loadGraph();
    });
  }

  refreshUserLabel();
  refreshRelationScoreText();
  loadGraph();
  loadDueReminders();

  if (window.UserContext) {
    window.UserContext.onChange(function () {
      refreshUserLabel();
      loadGraph();
      loadDueReminders();
    });
  }
})();
