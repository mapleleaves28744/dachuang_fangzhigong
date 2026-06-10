(function () {
  const API_BASE = window.ApiUtils.getApiBase();
  const parseApiResponse = window.ApiUtils.parseApiResponse;
  const withSuggestion = window.ApiUtils.withSuggestion;
  const KNOWLEDGE_UPDATED_AT_STORAGE_KEY = 'fangzhigong_knowledge_updated_at';

  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
  }

  const dom = {
    graph: document.getElementById('graph'),
    graphMeta: document.getElementById('graphMeta'),
    graphOverview: document.getElementById('graphOverview'),
    masteryBand: document.getElementById('masteryBand'),
    nodeTag: document.getElementById('nodeTag'),
    nodeName: document.getElementById('nodeName'),
    nodeDesc: document.getElementById('nodeDesc'),
    nodeDifficulty: document.getElementById('nodeDifficulty'),
    nodeMastery: document.getElementById('nodeMastery'),
    nodeInsight: document.getElementById('nodeInsight'),
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
    documentMentionList: document.getElementById('documentMentionList'),
    weakConceptList: document.getElementById('weakConceptList'),
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

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      const entityMap = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      };
      return entityMap[char] || char;
    });
  }

  function toNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : (typeof fallback === 'number' ? fallback : 0);
  }

  function getNodeId(node) {
    return String(node && (node.id || node.name) || '');
  }

  function getNodeType(node) {
    return String(node && node.node_type || 'concept');
  }

  function isConceptNode(node) {
    return getNodeType(node) === 'concept';
  }

  function isDocumentNode(node) {
    return getNodeType(node) === 'document';
  }

  function getConceptNodes(nodes) {
    return (Array.isArray(nodes) ? nodes : []).filter(isConceptNode);
  }

  function getDocumentNodes(nodes) {
    return (Array.isArray(nodes) ? nodes : []).filter(isDocumentNode);
  }

  function getLinkEndpointId(value) {
    if (value && typeof value === 'object') {
      return getNodeId(value);
    }
    return String(value || '');
  }

  function setConceptControlsEnabled(enabled) {
    const disabled = !enabled;
    if (dom.masteryRange) {
      dom.masteryRange.disabled = disabled;
      dom.masteryRange.style.opacity = disabled ? '0.55' : '1';
    }
    if (dom.saveMasteryBtn) {
      dom.saveMasteryBtn.disabled = disabled;
      dom.saveMasteryBtn.style.opacity = disabled ? '0.55' : '1';
      dom.saveMasteryBtn.title = disabled ? '仅概念节点支持掌握度更新' : '';
    }
    if (dom.deleteNodeBtn) {
      dom.deleteNodeBtn.disabled = disabled;
      dom.deleteNodeBtn.style.opacity = disabled ? '0.55' : '1';
      dom.deleteNodeBtn.title = disabled ? '仅概念节点支持删除操作' : '';
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

  function formatDateLabel(value) {
    const text = String(value || '').trim();
    if (!text) return '--';
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${month}-${day}`;
  }

  function buildNodeInsight(node) {
    if (!node) {
      return '选择节点后，这里会结合掌握度、难度和文档关联给出当前学习建议。';
    }

    const nodeId = getNodeId(node);
    const linkedCount = (state.graph.links || []).filter(function (item) {
      return getLinkEndpointId(item.source) === nodeId || getLinkEndpointId(item.target) === nodeId;
    }).length;

    if (isDocumentNode(node)) {
      const mentionCount = toNumber(node.mention_count, Array.isArray(node.mentions) ? node.mentions.length : 0);
      if (!mentionCount) {
        return `“${node.name}”已经同步到图谱，但当前还没有挂接明确概念。可以继续补充正文或在聊天页重新入库，让文档和知识点关系更完整。`;
      }
      return `“${node.name}”当前挂接了 ${mentionCount} 个概念节点，并保留 ${linkedCount} 条图谱关系。适合从这里反查“这份资料覆盖了哪些知识点”，再回到概念节点继续补掌握度。`;
    }

    const mastery = toNumber(node.mastery, 0);
    const difficulty = toNumber(node.difficulty, 0);

    if (mastery < 0.4) {
      return `“${node.name}”当前掌握偏弱，建议先回看定义和基础例题，再补 2-3 道同类型题。该节点当前关联 ${linkedCount} 条知识关系，适合结合前置知识一起补。`;
    }
    if (mastery < 0.7) {
      return `“${node.name}”已经有一定基础，但还没稳定下来。更适合做同题型迁移训练，尤其是把步骤写完整。当前难度约 ${Math.round(difficulty * 100)}%。`;
    }
    return `“${node.name}”整体掌握较稳，可以继续通过限时练习和跨知识点题目巩固迁移能力。当前图谱中与它直接相关的节点有 ${linkedCount} 个方向。`;
  }

  function setSelectedNode(node) {
    state.selectedNode = node;
    const mastery = toNumber(node && node.mastery, 0);
    const difficulty = toNumber(node && node.difficulty, 0);
    const documentNode = isDocumentNode(node);
    const mentions = Array.isArray(node && node.mentions) ? node.mentions.filter(Boolean) : [];
    dom.nodeTag.textContent = documentNode ? '已选择文档' : '已选择概念';
    dom.nodeName.textContent = node.name;
    dom.nodeDesc.textContent = documentNode
      ? ((mentions.length ? `提及概念：${mentions.join('、')}` : '') || node.description || '已同步文档')
      : (node.description || '-');
    dom.nodeDifficulty.textContent = documentNode
      ? (node.source ? `来源：${node.source}` : '文档节点')
      : (Math.round(difficulty * 100) + '%');
    dom.nodeMastery.textContent = documentNode
      ? `关联 ${toNumber(node.mention_count, mentions.length)} 个概念`
      : masteryToLabel(mastery);
    dom.masteryRange.value = Math.round(mastery * 100);
    setConceptControlsEnabled(!documentNode);
    if (dom.nodeInsight) {
      dom.nodeInsight.textContent = buildNodeInsight(node);
    }
  }

  function clearSelectedNode() {
    state.selectedNode = null;
    dom.nodeTag.textContent = '未选择节点';
    dom.nodeName.textContent = '-';
    dom.nodeDesc.textContent = '-';
    dom.nodeDifficulty.textContent = '-';
    dom.nodeMastery.textContent = '-';
    dom.masteryRange.value = 30;
    setConceptControlsEnabled(false);
    if (dom.nodeInsight) {
      dom.nodeInsight.textContent = buildNodeInsight(null);
    }
  }

  function renderStats(nodes, links) {
    const conceptNodes = getConceptNodes(nodes);
    const documentNodes = getDocumentNodes(nodes);
    const avg = conceptNodes.length
      ? (conceptNodes.reduce((sum, n) => sum + toNumber(n.mastery, 0), 0) / conceptNodes.length)
      : 0;
    const weak = conceptNodes.filter(n => toNumber(n.mastery, 0) < 0.4).length;
    const solid = conceptNodes.filter(n => toNumber(n.mastery, 0) >= 0.8).length;
    const mentionEdges = (links || []).filter(function (item) {
      return (item || {}).edge_type === 'mention' || String((item || {}).label || '').toUpperCase() === 'MENTIONS';
    }).length;

    dom.statsChips.innerHTML = [
      `节点数: ${nodes.length}`,
      `概念节点: ${conceptNodes.length}`,
      `文档节点: ${documentNodes.length}`,
      `关系数: ${links.length}`,
      `MENTIONS: ${mentionEdges}`,
      `平均掌握度: ${Math.round(avg * 100)}%`,
      `薄弱点: ${weak}`,
      `熟练点: ${solid}`
    ].map(t => `<span class="chip">${t}</span>`).join('');

    if (dom.graphOverview) {
      dom.graphOverview.innerHTML = `
        <div class="overview-tile">
          <div class="overview-tile-label">平均掌握度</div>
          <div class="overview-tile-value">${Math.round(avg * 100)}%</div>
          <div class="overview-tile-note">只统计概念节点，适合观察当前整体状态</div>
        </div>
        <div class="overview-tile">
          <div class="overview-tile-label">概念节点</div>
          <div class="overview-tile-value">${conceptNodes.length}</div>
          <div class="overview-tile-note">支持掌握度更新、路径规划与弱项筛查</div>
        </div>
        <div class="overview-tile">
          <div class="overview-tile-label">文档节点</div>
          <div class="overview-tile-value">${documentNodes.length}</div>
          <div class="overview-tile-note">显示已经同步到图谱的资料与笔记</div>
        </div>
        <div class="overview-tile">
          <div class="overview-tile-label">MENTIONS 关系</div>
          <div class="overview-tile-value">${mentionEdges}</div>
          <div class="overview-tile-note">表示文档和概念之间已经建立映射</div>
        </div>
      `;
    }

    if (dom.masteryBand) {
      const sorted = conceptNodes.slice().sort(function (a, b) {
        return Number(a.mastery || 0) - Number(b.mastery || 0);
      });
      dom.masteryBand.innerHTML = sorted.length
        ? sorted.slice(0, 8).map(function (node) {
            const mastery = Number(node.mastery || 0);
            const bandClass = mastery >= 0.8 ? 'strong' : (mastery >= 0.4 ? 'mid' : 'weak');
            return `<span class="band-pill"><span class="band-dot ${bandClass}"></span>${escapeHtml(node.name)} · ${Math.round(mastery * 100)}%</span>`;
          }).join('')
        : '<span class="chip">等待图谱数据</span>';
    }

    if (dom.weakConceptList) {
      const weakNodes = conceptNodes
        .slice()
        .sort(function (a, b) { return Number(a.mastery || 0) - Number(b.mastery || 0); })
        .slice(0, 5);
      dom.weakConceptList.innerHTML = weakNodes.length
        ? weakNodes.map(function (node) {
            const mastery = Math.round(Number(node.mastery || 0) * 100);
            return `<div class="mini-stack-item"><strong>${escapeHtml(node.name)}</strong><br>掌握度 ${mastery}% · ${mastery < 40 ? '先补定义和基础题' : '适合继续巩固步骤应用'}</div>`;
          }).join('')
        : '<div class="mini-stack-item">暂无节点数据</div>';
    }
  }

  function renderDocumentList(nodes) {
    if (!dom.documentMentionList) return;
    const documents = getDocumentNodes(nodes)
      .slice()
      .sort(function (a, b) {
        return toNumber(b.mention_count, 0) - toNumber(a.mention_count, 0);
      })
      .slice(0, 6);

    dom.documentMentionList.innerHTML = documents.length
      ? documents.map(function (node) {
          const mentions = Array.isArray(node.mentions) ? node.mentions.filter(Boolean) : [];
          const mentionText = mentions.length ? mentions.join('、') : '暂未提及概念';
          const sourceText = node.source ? `来源 ${escapeHtml(node.source)}` : '来源未标注';
          return `<div class="mini-stack-item"><strong>${escapeHtml(node.name)}</strong><br>${sourceText}<br>MENTIONS：${escapeHtml(mentionText)}</div>`;
        }).join('')
      : '<div class="mini-stack-item">当前图谱中还没有同步文档节点</div>';
  }

  function renderTargetSelect(nodes) {
    const conceptNodes = getConceptNodes(nodes);
    dom.targetSelect.innerHTML = conceptNodes
      .map(n => `<option value="${escapeHtml(n.name)}">${escapeHtml(n.name)}</option>`)
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
            if (isDocumentNode(d)) {
              const mentions = Array.isArray(d.mentions) ? d.mentions.filter(Boolean) : [];
              return [
                `<strong>${escapeHtml(d.name)}</strong>`,
                `类型: 文档节点`,
                `来源: ${escapeHtml(d.source || '-')}`,
                `关联概念: ${escapeHtml(String(toNumber(d.mention_count, mentions.length)))}`,
                `说明: ${escapeHtml(d.description || '-')}`
              ].join('<br>');
            }
            return [
              `<strong>${escapeHtml(d.name)}</strong>`,
              `类型: 概念节点`,
              `掌握度: ${Math.round((d.mastery || 0) * 100)}%`,
              `难度: ${Math.round((d.difficulty || 0) * 100)}%`,
              `描述: ${escapeHtml(d.description || '-')}`
            ].join('<br>');
          }
          const edge = params.data || {};
          return `${escapeHtml(edge.source_label || edge.source || '')} → ${escapeHtml(edge.target_label || edge.target || '')}<br>关系: ${escapeHtml(edge.label || '相关')}`;
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
            symbol: isDocumentNode(n) ? 'roundRect' : 'circle',
            symbolSize: isDocumentNode(n)
              ? (34 + Math.round(toNumber(n.mention_count, 0) * 4))
              : (26 + Math.round((n.mastery || 0) * 28)),
            itemStyle: {
              color: isDocumentNode(n) ? '#2563eb' : masteryToColor(n.mastery || 0),
              borderWidth: 2,
              borderColor: isDocumentNode(n) ? '#dbeafe' : '#ffffff'
            }
          })),
          links: (links || []).map(function (link) {
            const mentionEdge = (link || {}).edge_type === 'mention' || String((link || {}).label || '').toUpperCase() === 'MENTIONS';
            return {
              ...link,
              lineStyle: mentionEdge
                ? {
                    color: '#60a5fa',
                    opacity: 0.9,
                    width: 1.6,
                    type: 'dashed',
                    curveness: 0.12
                  }
                : {
                    color: '#94a3b8',
                    opacity: 0.8,
                    width: 1.5,
                    curveness: 0.1
                  }
            };
          })
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
      const resp = await fetch(`${API_BASE}/api/knowledge_graph?user_id=${getUserId()}&min_relation_score=${encodeURIComponent(threshold.toFixed(2))}&include_documents=true`);
      const data = await parseApiResponse(resp);

      const graphPayload = data && typeof data.graph === 'object' ? data.graph : {};
      state.graph = {
        nodes: Array.isArray(graphPayload.nodes) ? graphPayload.nodes : [],
        links: Array.isArray(graphPayload.links) ? graphPayload.links : []
      };
      renderGraph(state.graph.nodes, state.graph.links);
      renderTargetSelect(state.graph.nodes);
      renderStats(state.graph.nodes, state.graph.links);
      renderDocumentList(state.graph.nodes);

      const conceptNodes = getConceptNodes(state.graph.nodes);
      if (conceptNodes.length > 0) {
        setSelectedNode(conceptNodes[0]);
      } else if (state.graph.nodes.length > 0) {
        setSelectedNode(state.graph.nodes[0]);
      } else {
        clearSelectedNode();
      }

      const resolvedThreshold = data.min_relation_score == null ? threshold : toNumber(data.min_relation_score, threshold);
      const nodeCount = toNumber(data.node_count, state.graph.nodes.length);
      const edgeCount = toNumber(data.edge_count, state.graph.links.length);
      const documentCount = toNumber(data.document_count, getDocumentNodes(state.graph.nodes).length);
      const mentionCount = toNumber(data.mention_count, (state.graph.links || []).filter(function (item) {
        return (item || {}).edge_type === 'mention' || String((item || {}).label || '').toUpperCase() === 'MENTIONS';
      }).length);
      dom.graphMeta.textContent = `节点 ${nodeCount} · 文档 ${documentCount} · 关系 ${edgeCount} · MENTIONS ${mentionCount} · 阈值 ${Math.round(resolvedThreshold * 100)}% · 已更新`;
    } catch (err) {
      dom.graphMeta.textContent = '加载失败';
      dom.pathList.textContent = withSuggestion('图谱数据加载失败', err, '确认后端已启动并刷新页面');
      if (dom.documentMentionList) {
        dom.documentMentionList.innerHTML = '<div class="mini-stack-item">文档映射加载失败</div>';
      }
      console.error(err);
    }
  }

  async function pollTaskUntilDone(taskId, timeoutMs) {
    const start = Date.now();
    let lastState = 'PENDING';

    while (Date.now() - start < timeoutMs) {
      try {
        const resp = await fetch(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}`);
        const data = await parseApiResponse(resp);
        lastState = String(data.state || 'PENDING').toUpperCase();

        if (lastState === 'SUCCESS') {
          return { ok: true, state: lastState, result: data.result || {} };
        }

        if (lastState === 'FAILURE' || lastState === 'REVOKED') {
          return {
            ok: false,
            state: lastState,
            error: data.error || data.error_message || '任务失败'
          };
        }
      } catch (err) {
        // 轮询期间偶发错误可重试。
      }

      await new Promise(resolve => setTimeout(resolve, 700));
    }

    return {
      ok: false,
      state: 'TIMEOUT',
      error: `异步任务未在预期时间完成（最后状态: ${lastState}）`
    };
  }

  async function monitorGraphSync(graphSync, contextLabel) {
    if (!graphSync || graphSync.mode !== 'async' || !graphSync.task_id) {
      return { ok: true, state: 'SYNC_OR_DISABLED' };
    }

    const taskResult = await pollTaskUntilDone(graphSync.task_id, 15000);
    if (!taskResult.ok) {
      console.warn(`${contextLabel}图谱异步同步未确认`, taskResult.state, taskResult.error || '', graphSync.task_id);
    }
    return taskResult;
  }

  async function saveMastery() {
    if (!state.selectedNode) {
      alert('请先在图谱中选择一个知识点。');
      return;
    }
    if (!isConceptNode(state.selectedNode)) {
      alert('当前选中的是文档节点，请切换到概念节点后再调整掌握度。');
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
      const data = await parseApiResponse(resp);
      await monitorGraphSync(data.graph_sync, '掌握度更新：');
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
    if (!isConceptNode(state.selectedNode)) {
      alert('文档节点仅用于展示映射关系，暂不支持在此页面删除。');
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
      const data = await parseApiResponse(resp);
      await monitorGraphSync(data.graph_sync, '删除节点：');

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
      dom.pathList.textContent = '当前没有可规划的概念节点，请先同步或抽取知识点。';
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
        .map((step, idx) => `${idx + 1}. ${escapeHtml(step)}`)
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
      await monitorGraphSync(data.graph_sync, '文本抽取：');

      const concepts = Array.isArray(data.detected_concepts) && data.detected_concepts.length
        ? data.detected_concepts.map(escapeHtml).join('、')
        : '无';
      const rels = Array.isArray(data.relations) && data.relations.length
        ? data.relations.map(function (r) {
            return `${escapeHtml(r.source)} -> ${escapeHtml(r.target)}`;
          }).join('；')
        : '无';
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
        const overdueText = Number(item.overdue_days || 0) > 0 ? `已逾期 ${Number(item.overdue_days || 0)} 天` : `建议复习 ${formatDateLabel(item.next_review)}`;
        return `<div style="padding:8px 0; border-bottom:1px dashed #e2e8f0;"><strong>${escapeHtml(item.concept)}</strong> · 掌握度 ${pct}%<br><span style="color:#64748b; font-size:12px;">${escapeHtml(overdueText)}</span></div>`;
      }).join('');
    } catch (err) {
      dom.dueReminderList.textContent = withSuggestion('复习提醒加载失败', err, '刷新页面或稍后重试');
      console.error(err);
    }
  }

  function refreshUserLabel() {
    if (dom.mapUserLabel) {
      const userLabel = (window.UserContext && typeof window.UserContext.getUserLabel === 'function')
        ? window.UserContext.getUserLabel()
        : getUserId();
      dom.mapUserLabel.textContent = `当前用户：${userLabel}`;
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
  if (window.PageShell && typeof window.PageShell.initGlobalSidebar === 'function') {
    window.PageShell.initGlobalSidebar();
  }
  refreshRelationScoreText();
  loadGraph();
  loadDueReminders();
  window.addEventListener('knowledge:updated', function () {
    loadGraph();
    loadDueReminders();
  });

  window.addEventListener('storage', function (event) {
    if (!event || event.key !== KNOWLEDGE_UPDATED_AT_STORAGE_KEY) return;
    loadGraph();
    loadDueReminders();
  });

  if (window.UserContext) {
    window.UserContext.onChange(function () {
      refreshUserLabel();
      loadGraph();
      loadDueReminders();
    });
  }
})();
