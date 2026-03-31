(function () {
  const API_BASE = window.ApiUtils.getApiBase();
  const parseApiResponse = window.ApiUtils.parseApiResponse;
  const withSuggestion = window.ApiUtils.withSuggestion;
  const SUMMARY_POLL_INTERVAL_MS = 15000;
  const LIVE_STAY_TICK_INTERVAL_MS = 10000;

  const dashboardState = {
    summary: null,
    summaryLoading: false,
    summaryPromise: null,
    summaryPollTimer: 0,
    liveStayTimer: 0,
    activeDrawerPanel: ''
  };

  const styleLabelMap = {
    visual: '视觉型学习者',
    auditory: '听觉型学习者',
    kinesthetic: '动觉型学习者'
  };

  const methodLabelMap = {
    kmeans: 'KMeans聚类',
    rule: '规则推断',
    rule_fallback: '规则回退'
  };

  const categoryLabelMap = {
    knowledge: '知识性错误',
    skill: '技能性错误',
    habit: '习惯性错误',
    unknown: '未分类错误'
  };

  const severityLabelMap = {
    high: '高风险',
    medium: '需跟进',
    low: '可观察'
  };

  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
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
    const nextFallback = typeof fallback === 'number' ? fallback : 0;
    const num = Number(value);
    return Number.isFinite(num) ? num : nextFallback;
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value == null || value === '' ? '--' : String(value);
  }

  function setHtml(id, html) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = html || '';
  }

  function getCurrentPageId() {
    return window.PageShell && typeof window.PageShell.getCurrentPageId === 'function'
      ? window.PageShell.getCurrentPageId()
      : 'dashboard';
  }

  function getLiveStaySeconds() {
    return window.PageShell && typeof window.PageShell.getLiveStaySeconds === 'function'
      ? Math.max(0, toNumber(window.PageShell.getLiveStaySeconds(getCurrentPageId()), 0))
      : 0;
  }

  function getDisplayedStayMinutes(dataPool) {
    const pool = dataPool && typeof dataPool === 'object' ? dataPool : {};
    const estimatedMinutes = Math.max(0, toNumber(pool.estimated_stay_minutes, 0));
    const measuredTodayMinutes = Math.max(0, toNumber(pool.measured_stay_minutes_today, estimatedMinutes));
    const liveMeasuredMinutes = Math.round((measuredTodayMinutes * 60 + getLiveStaySeconds()) / 60);
    return Math.max(estimatedMinutes, liveMeasuredMinutes, 0);
  }

  function renderLiveStayMinutes() {
    const dataPool = dashboardState.summary && dashboardState.summary.data_pool ? dashboardState.summary.data_pool : {};
    setText('data-stay-minutes', `${getDisplayedStayMinutes(dataPool)}分`);
  }

  function createPillMarkup(label, muted) {
    return `<span class="pill${muted ? ' muted' : ''}">${escapeHtml(label)}</span>`;
  }

  function formatDateLabel(value) {
    const text = String(value || '').trim();
    if (!text) return '--';

    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;

    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hour}:${minute}`;
  }

  function shortText(value, limit) {
    const text = String(value == null ? '' : value).trim();
    const maxLen = Math.max(1, toNumber(limit, 12));
    if (text.length <= maxLen) return text;
    return `${text.slice(0, maxLen)}…`;
  }

  function normalizeStylePercent(styleScores) {
    const raw = {
      visual: Math.max(0, toNumber(styleScores && styleScores.visual, 0)),
      auditory: Math.max(0, toNumber(styleScores && styleScores.auditory, 0)),
      kinesthetic: Math.max(0, toNumber(styleScores && styleScores.kinesthetic, 0))
    };

    const maxValue = Math.max(raw.visual, raw.auditory, raw.kinesthetic);
    if (maxValue <= 0) {
      return { visual: 0, auditory: 0, kinesthetic: 0 };
    }

    if (maxValue <= 1) {
      return {
        visual: Math.round(raw.visual * 100),
        auditory: Math.round(raw.auditory * 100),
        kinesthetic: Math.round(raw.kinesthetic * 100)
      };
    }

    return {
      visual: Math.round(raw.visual),
      auditory: Math.round(raw.auditory),
      kinesthetic: Math.round(raw.kinesthetic)
    };
  }

  function formatStrategyTag(tag) {
    const raw = String(tag || '').trim();
    const parts = raw.split(':');
    if (parts.length !== 2) return raw;

    const key = parts[0];
    const val = parts[1];

    if (key === 'style') {
      return styleLabelMap[val] ? `风格: ${styleLabelMap[val]}` : `风格: ${val}`;
    }
    if (key === 'channel') {
      if (val === 'visual') return '通道: 图文呈现';
      if (val === 'auditory') return '通道: 听讲引导';
      if (val === 'kinesthetic') return '通道: 练习操作';
      return `通道: ${val}`;
    }
    if (key === 'method') {
      return methodLabelMap[val] ? `画像: ${methodLabelMap[val]}` : `画像: ${val}`;
    }
    return raw;
  }

  function strongestStyleKey(styleScores) {
    const entries = Object.entries(styleScores || {});
    if (!entries.length) return '';
    entries.sort(function (a, b) {
      return toNumber(b[1], 0) - toNumber(a[1], 0);
    });
    return entries[0][0] || '';
  }

  function renderPillList(id, items, formatter, emptyLabel) {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      setHtml(id, createPillMarkup(emptyLabel || '暂无数据', true));
      return;
    }
    setHtml(id, list.map(function (item) {
      return createPillMarkup(formatter(item), false);
    }).join(''));
  }

  function renderDataPool(summary) {
    const dataPool = summary && summary.data_pool ? summary.data_pool : {};
    const interaction = dataPool.interaction_breakdown || {};
    const totalRecords = toNumber(dataPool.total_records, 0);
    const learningContentRecords = toNumber(dataPool.learning_content_record_count, 0);
    const spaceContentCount = toNumber(dataPool.space_content_count, 0);
    const spaceCount = toNumber(dataPool.space_count, 0);
    const questionDrawCount = toNumber(dataPool.question_draw_count, toNumber(interaction.question_draw, 0));
    const questionAnswerCount = toNumber(dataPool.question_answer_count, toNumber(interaction.question_answer, 0));
    const diagnosisCount = toNumber(dataPool.diagnosis_count, toNumber(interaction.diagnosis, 0));
    const wrongQuestionCount = toNumber(dataPool.wrong_question_count, toNumber(interaction.wrong_questions, 0));
    const qaSampleTotal = toNumber(dataPool.qa_sample_total, toNumber(interaction.qa_sample_total, 0));
    const dataSourceTotal = totalRecords + spaceContentCount;

    setText('data-source-total', dataSourceTotal);
    setText('data-learning-content', `${learningContentRecords}条 / ${spaceContentCount}份`);
    setText(
      'data-learning-content-note',
      spaceContentCount > 0
        ? `已从 ${spaceCount} 个空间读取 ${spaceContentCount} 份现有内容，并累计沉淀 ${learningContentRecords} 条学习记录`
        : '当前还没有空间内容，上传资料后这里会自动读取并统计'
    );
    setText('data-qa-count', `${qaSampleTotal}条 / ${wrongQuestionCount}题`);
    setText('data-qa-note', `抽题 ${questionDrawCount} 次 · 作答 ${questionAnswerCount} 次 · 诊断 ${diagnosisCount} 条`);
    setText('data-active-days', toNumber(dataPool.active_days, 0));
    renderLiveStayMinutes();

    renderPillList(
      'dashboard-topics',
      Array.isArray(dataPool.top_topics) ? dataPool.top_topics.slice(0, 3) : [],
      function (item) {
        return `${item.topic} · ${toNumber(item.count, 0)}次`;
      },
      '等待主题沉淀'
    );

    renderPillList(
      'dashboard-study-windows',
      Array.isArray(dataPool.study_windows) ? dataPool.study_windows.slice(0, 3) : [],
      function (item) {
        const durationMinutes = Math.round(toNumber(item.duration_seconds, 0) / 60);
        return durationMinutes > 0
          ? `${item.label} · ${toNumber(item.count, 0)}次 · ${durationMinutes}分`
          : `${item.label} · ${toNumber(item.count, 0)}次`;
      },
      '等待行为数据'
    );
  }

  function renderKnowledgeInsights(summary) {
    const graphInsights = summary && summary.graph_insights ? summary.graph_insights : {};
    const review = summary && summary.review ? summary.review : {};
    const graph = summary && summary.graph ? summary.graph : {};
    const graphSize = graphInsights.graph_size || {};
    const heatmap = Array.isArray(graphInsights.mastery_heatmap) ? graphInsights.mastery_heatmap : [];
    const dependencyChain = Array.isArray(graphInsights.dependency_chain) ? graphInsights.dependency_chain : [];
    const sourceTrace = Array.isArray(graphInsights.concept_source_trace) ? graphInsights.concept_source_trace : [];
    const distribution = graphInsights.distribution || {};
    const reviewForecast = graphInsights.review_forecast || {};

    const overallMastery = Math.round(toNumber(summary && summary.overall_mastery, 0) * 100);
    setText('overall-mastery', `${overallMastery}%`);
    setText('kg-overall-mastery', `${overallMastery}%`);
    setText('graph-node-count', toNumber(graphSize.nodes, toNumber(graph.node_count, 0)));
    setText('graph-edge-count', toNumber(graphSize.edges, toNumber(graph.edge_count, 0)));
    setText('kg-node-count', toNumber(graphSize.nodes, toNumber(graph.node_count, 0)));
    setText('kg-edge-count', toNumber(graphSize.edges, toNumber(graph.edge_count, 0)));
    setText('kg-due-count', toNumber(review.due_count, 0));
    setText('kg-upcoming-count', toNumber(review.upcoming_count, 0));

    const weakCount = toNumber(distribution.weak, 0);
    const mediumCount = toNumber(distribution.medium, 0);
    const strongCount = toNumber(distribution.strong, 0);
    const totalCount = Math.max(weakCount + mediumCount + strongCount, 1);
    const weakestItem = heatmap[0] || null;

    setHtml('dashboard-mastery-spectrum', heatmap.length
      ? `
          <div class="spectrum-bar">
            <div class="spectrum-segment weak" style="width:${(weakCount / totalCount) * 100}%"></div>
            <div class="spectrum-segment medium" style="width:${(mediumCount / totalCount) * 100}%"></div>
            <div class="spectrum-segment strong" style="width:${(strongCount / totalCount) * 100}%"></div>
          </div>
          <div class="spectrum-legend">
            <div class="spectrum-legend-item">
              <div class="spectrum-legend-label"><span class="spectrum-dot weak"></span>薄弱区</div>
              <div class="spectrum-legend-value">${weakCount}</div>
            </div>
            <div class="spectrum-legend-item">
              <div class="spectrum-legend-label"><span class="spectrum-dot medium"></span>过渡区</div>
              <div class="spectrum-legend-value">${mediumCount}</div>
            </div>
            <div class="spectrum-legend-item">
              <div class="spectrum-legend-label"><span class="spectrum-dot strong"></span>稳定区</div>
              <div class="spectrum-legend-value">${strongCount}</div>
            </div>
          </div>
        `
      : '<div class="empty-state">暂无知识点样本，答题与内容录入后会自动形成掌握分层。</div>');

    setHtml('dashboard-mastery-story', heatmap.length
      ? `当前共追踪 <strong>${totalCount}</strong> 个知识点，其中薄弱区 <strong>${weakCount}</strong> 个，稳定区 <strong>${strongCount}</strong> 个。${weakestItem ? `当前最需要优先回看的知识点是“${escapeHtml(weakestItem.concept || '未命名知识点')}”，掌握度约 ${toNumber(weakestItem.mastery, 0)}%。` : ''}`
      : '当前还没有足够的知识点样本，完成练习后这里会自动生成掌握走势解读。');

    setHtml('dashboard-review-forecast', heatmap.length
      ? `
          <div class="forecast-card">
            <div class="forecast-card-label">今日到期</div>
            <div class="forecast-card-value">${toNumber(reviewForecast.due_count, toNumber(review.due_count, 0))}</div>
            <div class="forecast-card-note">适合优先安排短时复习</div>
          </div>
          <div class="forecast-card">
            <div class="forecast-card-label">待安排</div>
            <div class="forecast-card-value">${toNumber(reviewForecast.upcoming_count, toNumber(review.upcoming_count, 0))}</div>
            <div class="forecast-card-note">后续可穿插到学习计划中</div>
          </div>
          <div class="forecast-card">
            <div class="forecast-card-label">薄弱知识点</div>
            <div class="forecast-card-value">${toNumber(reviewForecast.weak_concept_count, weakCount)}</div>
            <div class="forecast-card-note">建议结合依赖链反向补强</div>
          </div>
        `
      : '<div class="empty-state">暂无复习预测数据</div>');

    setHtml('dashboard-mastery-heatmap', heatmap.length
      ? heatmap.map(function (item) {
        const mastery = toNumber(item.mastery, 0);
        const note = item.due
          ? `需要优先复习${toNumber(item.overdue_days, 0) > 0 ? `，已逾期 ${toNumber(item.overdue_days, 0)} 天` : ''}`
          : (item.next_review ? `下次建议复习 ${escapeHtml(formatDateLabel(item.next_review))}` : '等待后续复习安排');
        const sourceTitles = Array.isArray(item.source_titles) ? item.source_titles.slice(0, 2) : [];
        const tags = [
          item.due ? '优先复习' : '跟踪中',
          `${toNumber(item.review_count, 0)} 次练习`
        ].concat(sourceTitles.map(function (title) {
          return shortText(title, 10);
        })).slice(0, 4);
          return `
            <div class="mastery-cell ${escapeHtml(item.status || 'warn')}">
              <div class="mastery-cell-head">
                <span class="mastery-cell-title">${escapeHtml(item.concept || '未命名知识点')}</span>
                <span class="mastery-cell-score">${mastery}%</span>
              </div>
              <div class="mastery-cell-body">
                <div class="mini-bar"><div class="mini-bar-fill" style="width:${Math.max(0, Math.min(100, mastery))}%"></div></div>
                <div class="mastery-cell-meta">${note}</div>
                <div class="mastery-cell-tags">
                  ${tags.map(function (tag) { return `<span class="mini-pill">${escapeHtml(tag)}</span>`; }).join('')}
                </div>
              </div>
            </div>
          `;
        }).join('')
      : '<div class="empty-state">暂无学生知识点数据，后续会自动生成掌握热力图。</div>');

    setHtml('dashboard-dependency-chain', dependencyChain.length
      ? dependencyChain.map(function (item) {
          const path = Array.isArray(item.path) ? item.path : [];
          return `
            <div class="timeline-item">
              <div class="timeline-route">${path.map(function (segment, index) {
                return `${index > 0 ? '<span class="timeline-arrow">→</span>' : ''}${escapeHtml(segment)}`;
              }).join('')}</div>
              <div class="timeline-meta">${escapeHtml(item.reason || '可用于追溯前置知识和补强路径')}</div>
            </div>
          `;
        }).join('')
      : '<div class="empty-state">暂无可展示的知识依赖链</div>');

    setHtml('dashboard-concept-source-trace', sourceTrace.length
      ? sourceTrace.map(function (item) {
          const sources = Array.isArray(item.sources) ? item.sources : [];
          return `
            <div class="mini-item">
              <div class="mini-item-head">
                <span class="mini-item-title">${escapeHtml(item.concept || '未命名知识点')}</span>
                ${createPillMarkup(`掌握度 ${toNumber(item.mastery, 0)}%`, false)}
              </div>
              <div class="mini-item-desc">${sources.length ? escapeHtml(sources.join(' / ')) : '暂未追踪到明确学习来源'}</div>
              <div class="mini-item-meta">来源数 ${toNumber(item.source_count, 0)} · 便于回溯该知识点来自哪些学习内容</div>
            </div>
          `;
        }).join('')
      : '<div class="empty-state">暂无知识来源追踪数据</div>');
  }

  function renderProfile(summary) {
    const profile = summary && summary.profile ? summary.profile : {};
    const insights = summary && summary.profile_insights ? summary.profile_insights : {};
    const learningStyle = profile.learning_style || '';
    const styleText = insights.learning_style_label || styleLabelMap[learningStyle] || '综合型学习者';
    const styleMethodText = insights.style_method_label || methodLabelMap[profile.style_method] || (profile.style_method || '--');
    const styleScores = normalizeStylePercent(insights.style_scores || profile.style_scores || {});
    const interests = Array.isArray(insights.interests) ? insights.interests : [];
    const mediaPreferences = Array.isArray(insights.media_preferences) ? insights.media_preferences : [];
    const traits = Array.isArray(insights.profile_traits) ? insights.profile_traits : [];
    const strongestStyle = strongestStyleKey(styleScores);
    const primaryMedia = mediaPreferences.find(function (item) {
      return toNumber(item.count, 0) > 0;
    }) || null;
    const topInterest = interests[0] || null;
    const focusText = profile.focus_minutes ? `${profile.focus_minutes} 分钟` : '--';

    setText('dashboard-style', styleText);
    setText('dashboard-style-method', `画像推断方式: ${styleMethodText}`);
    setText('dashboard-best-time', `最佳学习时段: ${profile.best_time_range || '--'}`);
    setText('dashboard-focus', `注意力集中时间: ${profile.focus_minutes ? `${profile.focus_minutes} 分钟` : '--'}`);

    setText('style-score-visual', `${styleScores.visual}%`);
    setText('style-score-auditory', `${styleScores.auditory}%`);
    setText('style-score-kinesthetic', `${styleScores.kinesthetic}%`);
    const visualBar = document.getElementById('style-bar-visual');
    const auditoryBar = document.getElementById('style-bar-auditory');
    const kinestheticBar = document.getElementById('style-bar-kinesthetic');
    if (visualBar) visualBar.style.width = `${styleScores.visual}%`;
    if (auditoryBar) auditoryBar.style.width = `${styleScores.auditory}%`;
    if (kinestheticBar) kinestheticBar.style.width = `${styleScores.kinesthetic}%`;

    setHtml('dashboard-persona-stage', `
      <div class="persona-kicker">学习者画像</div>
      <div class="persona-title">${escapeHtml(styleText)}</div>
      <div class="persona-desc">
        ${escapeHtml(
          primaryMedia
            ? `当前最适合从“${primaryMedia.label}”切入，再围绕 ${profile.best_time_range || '稳定时段'} 安排学习。`
            : '当前画像样本仍在积累中，系统会持续根据内容互动和作答行为更新建议。'
        )}
      </div>
      <div class="persona-grid">
        <div class="persona-metric">
          <div class="persona-metric-label">主导风格</div>
          <div class="persona-metric-value">${escapeHtml(styleLabelMap[strongestStyle] || styleText)}</div>
          <div class="persona-metric-note">由内容偏好与学习行为联合推断</div>
        </div>
        <div class="persona-metric">
          <div class="persona-metric-label">常用输入通道</div>
          <div class="persona-metric-value">${escapeHtml(primaryMedia ? primaryMedia.label : '--')}</div>
          <div class="persona-metric-note">${primaryMedia ? `占比 ${toNumber(primaryMedia.percent, 0)}%` : '等待内容交互样本'}</div>
        </div>
        <div class="persona-metric">
          <div class="persona-metric-label">最佳学习时段</div>
          <div class="persona-metric-value">${escapeHtml(profile.best_time_range || '--')}</div>
          <div class="persona-metric-note">适合安排难题和理解型任务</div>
        </div>
        <div class="persona-metric">
          <div class="persona-metric-label">建议专注时长</div>
          <div class="persona-metric-value">${escapeHtml(focusText)}</div>
          <div class="persona-metric-note">${topInterest ? `近期对“${topInterest.topic}”更有持续投入` : '持续积累后会更准确'}</div>
        </div>
      </div>
    `);

    renderPillList(
      'dashboard-interests',
      interests,
      function (item) {
        return item.count ? `${item.topic} · ${item.source} · ${toNumber(item.count, 0)}次` : `${item.topic} · ${item.source}`;
      },
      '暂无兴趣特征'
    );

    setHtml('dashboard-interest-cloud', interests.length
      ? interests.slice(0, 8).map(function (item, index) {
          const count = Math.max(1, toNumber(item.count, 1));
          const fontSize = Math.min(17, 12 + count * 0.8 + Math.max(0, 4 - index));
          return `<span class="interest-bubble" style="font-size:${fontSize}px;">${escapeHtml(item.topic || '--')}<small>${escapeHtml(item.source || '兴趣')}</small></span>`;
        }).join('')
      : '<span class="pill muted">学习兴趣还在生成中</span>');

    setHtml('dashboard-media-preferences', mediaPreferences.length
      ? mediaPreferences.map(function (item) {
          const pct = Math.max(0, Math.min(100, toNumber(item.percent, 0)));
          return `
            <div class="mini-item">
              <div class="mini-item-head">
                <span class="mini-item-title">${escapeHtml(item.label || '--')}</span>
                ${createPillMarkup(`${toNumber(item.count, 0)} 次`, false)}
              </div>
              <div class="mini-bar"><div class="mini-bar-fill" style="width:${pct}%"></div></div>
              <div class="mini-item-meta">占当前内容交互 ${pct}%</div>
            </div>
          `;
        }).join('')
      : '<div class="empty-state">暂无内容交互偏好数据</div>');

    setHtml('dashboard-profile-traits', traits.length
      ? traits.map(function (item) {
          return `<div class="intervention-item">${escapeHtml(item)}</div>`;
        }).join('')
      : '<div class="empty-state">暂无可解释的画像证据</div>');
  }

  function renderDiagnosis(summary) {
    const diagnosis = summary && summary.diagnosis ? summary.diagnosis : {};
    const intervention = summary && summary.intervention_summary ? summary.intervention_summary : {};
    const categoryCount = diagnosis.category_count || {};
    const latestCases = Array.isArray(intervention.latest_cases) ? intervention.latest_cases : [];
    const actionQueue = Array.isArray(intervention.action_queue) ? intervention.action_queue : [];
    const resourceMix = Array.isArray(intervention.resource_mix) ? intervention.resource_mix : [];
    const fallbackLatest = Array.isArray(diagnosis.latest) ? diagnosis.latest : [];

    setText('diag-knowledge', `${toNumber(categoryCount.knowledge, 0)}次`);
    setText('diag-skill', `${toNumber(categoryCount.skill, 0)}次`);
    setText('diag-habit', `${toNumber(categoryCount.habit, 0)}次`);
    setText('diag-total', `${toNumber(diagnosis.total, 0)} 条诊断`);
    setText('dashboard-active-interventions', toNumber(intervention.pending_count, actionQueue.length));

    const diagnosisCategoryTotal =
      toNumber(categoryCount.knowledge, 0)
      + toNumber(categoryCount.skill, 0)
      + toNumber(categoryCount.habit, 0);
    const diagnosisTotal = Math.max(1, diagnosisCategoryTotal);
    const hasDiagnosisBalance = toNumber(diagnosis.total, 0) > 0 || diagnosisCategoryTotal > 0;
    setHtml('dashboard-diagnosis-balance', hasDiagnosisBalance
      ? `
          <div class="diagnosis-balance-bar">
            <div class="diagnosis-balance-segment knowledge" style="width:${(toNumber(categoryCount.knowledge, 0) / diagnosisTotal) * 100}%"></div>
            <div class="diagnosis-balance-segment skill" style="width:${(toNumber(categoryCount.skill, 0) / diagnosisTotal) * 100}%"></div>
            <div class="diagnosis-balance-segment habit" style="width:${(toNumber(categoryCount.habit, 0) / diagnosisTotal) * 100}%"></div>
          </div>
          <div class="diagnosis-legend">
            <div class="diagnosis-legend-item">
              知识性错误
              <strong>${toNumber(categoryCount.knowledge, 0)}</strong>
              说明基础概念或条件理解还不稳。
            </div>
            <div class="diagnosis-legend-item">
              技能性错误
              <strong>${toNumber(categoryCount.skill, 0)}</strong>
              更需要步骤训练和同题型迁移。
            </div>
            <div class="diagnosis-legend-item">
              习惯性错误
              <strong>${toNumber(categoryCount.habit, 0)}</strong>
              重点是节奏控制与检查动作。
            </div>
          </div>
        `
      : '<div class="empty-state">暂无可展示的错误结构分布。</div>');

    if (latestCases.length) {
      setHtml('dashboard-diagnosis-latest', latestCases.map(function (item) {
        const signals = Array.isArray(item.signals) && item.signals.length
          ? item.signals.join(' / ')
          : item.recommendation || '暂无附加诊断信号';
        return `
          <div class="mini-item">
            <div class="mini-item-head">
              <span class="mini-item-title">${escapeHtml(item.error_type || item.category_label || '认知诊断')}</span>
              ${createPillMarkup(item.category_label || '诊断', false)}
            </div>
            <div class="mini-item-desc">${escapeHtml(item.question_excerpt || '暂无题干')}</div>
            <div class="mini-item-meta">诊断时间 ${escapeHtml(formatDateLabel(item.timestamp))} · 诊断信号 ${escapeHtml(signals)}</div>
          </div>
        `;
      }).join(''));
    } else if (fallbackLatest.length) {
      setHtml('dashboard-diagnosis-latest', fallbackLatest.map(function (item) {
        const diag = item.diagnosis || {};
        const categoryText = categoryLabelMap[diag.category] || categoryLabelMap.unknown;
        const severityText = severityLabelMap[diag.severity] || '待观察';
        return `
          <div class="mini-item">
            <div class="mini-item-head">
              <span class="mini-item-title">${escapeHtml(diag.error_type || categoryText)}</span>
              ${createPillMarkup(severityText, false)}
            </div>
            <div class="mini-item-desc">${escapeHtml(String(item.question || '暂无题干').slice(0, 90))}</div>
            <div class="mini-item-meta">归因类别 ${escapeHtml(categoryText)} · ${escapeHtml(diag.recommendation || '建议继续积累诊断样本')}</div>
          </div>
        `;
      }).join(''));
    } else {
      setHtml('dashboard-diagnosis-latest', '<div class="empty-state">暂无诊断样本。完成题目作答与错题分析后，这里会展示最近的归因结果。</div>');
    }

    setHtml('dashboard-suggestions', actionQueue.length
      ? actionQueue.map(function (item) {
          const meta = [item.resource, item.time].filter(Boolean).join(' · ');
          const evidence = item.evidence ? ` 证据：${item.evidence}` : '';
          return `
            <div class="intervention-item">
              <strong>${escapeHtml(item.title || '个性化干预')}</strong><br>
              ${escapeHtml(item.reason || '结合图谱与画像生成的行动建议')}<br>
              ${escapeHtml(meta)}${escapeHtml(evidence)}
            </div>
          `;
        }).join('')
      : '<div class="empty-state">暂无补救措施建议</div>');

    renderPillList(
      'dashboard-resource-mix',
      resourceMix.filter(function (item) {
        return toNumber(item.count, 0) > 0;
      }),
      function (item) {
        return `${item.label} ${toNumber(item.count, 0)}次 · ${item.resource}`;
      },
      '等待诊断数据'
    );
  }

  function renderRecommendations(summary) {
    const container = document.getElementById('dashboard-recommendations');
    if (!container) return;

    const recommendations = Array.isArray(summary && summary.recommendations) ? summary.recommendations : [];
    const filterEl = document.getElementById('dashboard-rec-style-filter');
    const activeStyle = filterEl ? String(filterEl.value || 'all').trim() : 'all';

    const filtered = recommendations.filter(function (item) {
      if (activeStyle === 'all') return true;
      const tags = Array.isArray(item && item.strategy_tags) ? item.strategy_tags : [];
      return tags.some(function (tag) {
        return String(tag).trim() === `style:${activeStyle}`;
      });
    });

    if (!filtered.length) {
      container.innerHTML = '<div class="empty-state">当前筛选条件下暂无推荐资源，请继续积累学习画像和诊断样本。</div>';
      return;
    }

    container.innerHTML = filtered.map(function (item) {
      const tags = Array.isArray(item && item.strategy_tags) ? item.strategy_tags.slice(0, 3) : [];
      const tagMarkup = tags.length
        ? `<div class="pill-list">${tags.map(function (tag) {
            return createPillMarkup(formatStrategyTag(tag), false);
          }).join('')}</div>`
        : '';
      return `
        <div class="mini-item">
          <div class="mini-item-head">
            <span class="mini-item-title">${escapeHtml(item.title || '个性化学习资源')}</span>
            ${createPillMarkup(item.recommend_time || '--', false)}
          </div>
          <div class="mini-item-desc">${escapeHtml(item.reason || '结合当前学习状态生成的补救建议')}</div>
          <div class="mini-item-meta">资源类型 ${escapeHtml(item.resource_type || '个性化学习包')} · ${escapeHtml(item.evidence_brief || '暂无补充证据')}</div>
          ${tagMarkup}
        </div>
      `;
    }).join('');
  }

  function renderReviewReminders(summary) {
    const container = document.getElementById('dashboard-review-reminders');
    if (!container) return;

    const review = summary && summary.review ? summary.review : {};
    const dueItems = Array.isArray(review.due_items) ? review.due_items : [];
    const upcomingItems = Array.isArray(review.upcoming_items) ? review.upcoming_items : [];
    const displayItems = dueItems.length ? dueItems.slice(0, 5) : upcomingItems.slice(0, 5);

    if (!displayItems.length) {
      container.innerHTML = '<div class="empty-state">暂无复习计划，知识点积累后这里会自动安排基于遗忘曲线的复习提醒。</div>';
      return;
    }

    container.innerHTML = displayItems.map(function (item) {
      const mastery = Math.round(toNumber(item.mastery, 0) * 100);
      const hint = item.due
        ? `已到期${toNumber(item.overdue_days, 0) > 0 ? ` ${toNumber(item.overdue_days, 0)} 天` : ''}`
        : `建议时间 ${formatDateLabel(item.next_review)}`;
      return `
        <div class="review-card">
          <div>
            <div class="mini-item-title">${escapeHtml(item.concept || '未命名知识点')}</div>
            <div class="mini-item-desc">掌握度 ${mastery}% · ${escapeHtml(hint)}</div>
          </div>
          ${createPillMarkup(item.due ? '优先复习' : '待安排', false)}
        </div>
      `;
    }).join('');
  }

  function renderSummary(summary) {
    dashboardState.summary = summary || {};
    renderDataPool(dashboardState.summary);
    renderKnowledgeInsights(dashboardState.summary);
    renderProfile(dashboardState.summary);
    renderDiagnosis(dashboardState.summary);
    renderRecommendations(dashboardState.summary);
    renderReviewReminders(dashboardState.summary);
  }

  function renderSummaryLoadError(message) {
    const safeMessage = escapeHtml(message || '数据加载失败');
    const emptyMarkup = `<div class="empty-state">${safeMessage}</div>`;
    const pillMarkup = `<span class="pill muted">${safeMessage}</span>`;

    setText('data-learning-content-note', message);
    setText('data-qa-note', message);
    setHtml('dashboard-topics', pillMarkup);
    setHtml('dashboard-study-windows', pillMarkup);
    setHtml('dashboard-mastery-spectrum', emptyMarkup);
    setHtml('dashboard-mastery-story', emptyMarkup);
    setHtml('dashboard-review-forecast', emptyMarkup);
    setHtml('dashboard-mastery-heatmap', emptyMarkup);
    setHtml('dashboard-dependency-chain', emptyMarkup);
    setHtml('dashboard-concept-source-trace', emptyMarkup);
    setHtml('dashboard-persona-stage', emptyMarkup);
    setHtml('dashboard-interest-cloud', pillMarkup);
    setHtml('dashboard-media-preferences', emptyMarkup);
    setHtml('dashboard-profile-traits', emptyMarkup);
    setHtml('dashboard-diagnosis-balance', emptyMarkup);
    setHtml('dashboard-diagnosis-latest', emptyMarkup);
    setHtml('dashboard-suggestions', emptyMarkup);
    setHtml('dashboard-resource-mix', pillMarkup);
    setHtml('dashboard-recommendations', emptyMarkup);
    setHtml('dashboard-review-reminders', emptyMarkup);
  }

  async function loadDashboardSummary() {
    if (dashboardState.summaryLoading && dashboardState.summaryPromise) {
      return dashboardState.summaryPromise;
    }
    const userId = getUserId();
    dashboardState.summaryLoading = true;
    dashboardState.summaryPromise = (async function () {
      try {
        const response = await fetch(`${API_BASE}/api/dashboard/summary?user_id=${userId}`);
        const data = await parseApiResponse(response);
        renderSummary(data);
      } catch (error) {
        console.warn('仪表盘汇总加载失败:', error);
        const message = withSuggestion('仪表盘汇总加载失败', error, '刷新页面或稍后重试');
        if (!dashboardState.summary) {
          renderSummaryLoadError(message);
        } else {
          setText('data-learning-content-note', message);
          setText('data-qa-note', message);
          setHtml('dashboard-topics', `<span class="pill muted">${escapeHtml(message)}</span>`);
          setHtml('dashboard-study-windows', `<span class="pill muted">${escapeHtml(message)}</span>`);
        }
      } finally {
        dashboardState.summaryLoading = false;
        dashboardState.summaryPromise = null;
        renderLiveStayMinutes();
      }
    })();
    return dashboardState.summaryPromise;
  }

  function startDashboardAutoRefresh() {
    if (dashboardState.summaryPollTimer) {
      window.clearInterval(dashboardState.summaryPollTimer);
    }
    if (dashboardState.liveStayTimer) {
      window.clearInterval(dashboardState.liveStayTimer);
    }

    dashboardState.summaryPollTimer = window.setInterval(function () {
      if (document.hidden) return;
      loadDashboardSummary();
    }, SUMMARY_POLL_INTERVAL_MS);

    dashboardState.liveStayTimer = window.setInterval(function () {
      if (document.hidden) return;
      renderLiveStayMinutes();
    }, LIVE_STAY_TICK_INTERVAL_MS);
  }

  async function loadDashboardTodayTasks() {
    const userId = getUserId();
    const tasksDiv = document.getElementById('dashboard-today-tasks');
    if (!tasksDiv) return;

    try {
      const response = await fetch(`${API_BASE}/api/plans?user_id=${userId}`);
      const data = await parseApiResponse(response);

      if (!data.plans || data.plans.length === 0) {
        tasksDiv.innerHTML = '<div class="empty-state">暂无今日任务，可以先从推荐资源或复习安排中挑选一项开始。</div>';
        return;
      }

      tasksDiv.innerHTML = data.plans.map(function (plan) {
        const statusText = plan.completed ? '已完成' : '待执行';
        return `
          <div class="task-card">
            <div>
              <div class="mini-item-title">${escapeHtml(statusText)} · ${escapeHtml(plan.time || '--')}</div>
              <div class="mini-item-desc">${escapeHtml(plan.task || '未命名任务')}</div>
            </div>
            <button class="dashboard-inline-btn" type="button" onclick="deleteDashboardTask('${escapeHtml(plan.id || '')}')">删除</button>
          </div>
        `;
      }).join('');
    } catch (error) {
      tasksDiv.innerHTML = `<div class="empty-state">${escapeHtml(withSuggestion('任务加载失败', error, '刷新页面或稍后重试'))}</div>`;
    }
  }

  async function deleteDashboardTask(planId) {
    const userId = getUserId();
    if (!window.confirm('确定要删除这个任务吗？')) return;

    try {
      const response = await fetch(`${API_BASE}/api/plans/${planId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      await parseApiResponse(response);
      loadDashboardTodayTasks();
    } catch (error) {
      window.alert(withSuggestion('删除任务失败', error, '确认网络正常后再试'));
    }
  }

  function syncDashboardUserLabel() {
    const label = document.getElementById('dashboard-user-label');
    if (!label || !window.UserContext) return;
    const userLabel = typeof window.UserContext.getUserLabel === 'function'
      ? window.UserContext.getUserLabel()
      : window.UserContext.getUserId();
    label.textContent = `当前用户：${userLabel}`;
  }

  function syncDrawerTriggerState(activePanel) {
    const triggers = document.querySelectorAll('.hero-drawer-launcher[data-drawer-target]');
    triggers.forEach(function (trigger) {
      const isActive = !!activePanel && trigger.getAttribute('data-drawer-target') === activePanel;
      trigger.classList.toggle('active', isActive);
      trigger.setAttribute('aria-expanded', isActive ? 'true' : 'false');
    });
  }

  function setActiveDrawerPanel(panelKey) {
    const drawer = document.getElementById('dashboardDrawer');
    if (!drawer) return false;

    const panels = drawer.querySelectorAll('.dashboard-drawer-panel[data-panel]');
    let activePanel = null;
    panels.forEach(function (panel) {
      const isActive = panel.getAttribute('data-panel') === panelKey;
      panel.hidden = !isActive;
      if (isActive) {
        activePanel = panel;
      }
    });

    if (!activePanel) return false;

    const kicker = document.getElementById('dashboardDrawerKicker');
    const title = document.getElementById('dashboardDrawerTitle');
    const desc = document.getElementById('dashboardDrawerDesc');
    if (kicker) kicker.textContent = activePanel.getAttribute('data-kicker') || '按需查看';
    if (title) title.textContent = activePanel.getAttribute('data-title') || '详细内容';
    if (desc) desc.textContent = activePanel.getAttribute('data-desc') || '这里会显示所选模块的详细内容。';

    dashboardState.activeDrawerPanel = panelKey;
    syncDrawerTriggerState(panelKey);
    return true;
  }

  function closeDashboardDrawer() {
    const drawer = document.getElementById('dashboardDrawer');
    const backdrop = document.getElementById('dashboardDrawerBackdrop');
    if (!drawer || !backdrop) return;

    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    backdrop.classList.remove('show');
    document.body.classList.remove('dashboard-drawer-open');
    dashboardState.activeDrawerPanel = '';
    syncDrawerTriggerState('');
  }

  function openDashboardDrawer(panelKey) {
    const drawer = document.getElementById('dashboardDrawer');
    const backdrop = document.getElementById('dashboardDrawerBackdrop');
    if (!drawer || !backdrop) return;
    if (!setActiveDrawerPanel(panelKey)) return;

    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    backdrop.classList.add('show');
    document.body.classList.add('dashboard-drawer-open');
  }

  function initDashboardDrawer() {
    const drawer = document.getElementById('dashboardDrawer');
    const backdrop = document.getElementById('dashboardDrawerBackdrop');
    const closeButton = document.getElementById('dashboardDrawerClose');
    if (!drawer || !backdrop || !closeButton) return;

    document.querySelectorAll('.hero-drawer-launcher[data-drawer-target]').forEach(function (trigger) {
      trigger.addEventListener('click', function () {
        const panelKey = String(trigger.getAttribute('data-drawer-target') || '').trim();
        if (!panelKey) return;

        if (drawer.classList.contains('open') && dashboardState.activeDrawerPanel === panelKey) {
          closeDashboardDrawer();
          return;
        }

        openDashboardDrawer(panelKey);
      });
    });

    closeButton.addEventListener('click', closeDashboardDrawer);
    backdrop.addEventListener('click', closeDashboardDrawer);
    syncDrawerTriggerState('');

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && drawer.classList.contains('open')) {
        closeDashboardDrawer();
      }
    });
  }

  window.deleteDashboardTask = deleteDashboardTask;

  window.addEventListener('DOMContentLoaded', function () {
    if (window.PageShell && typeof window.PageShell.initGlobalSidebar === 'function') {
      window.PageShell.initGlobalSidebar();
    }

    initDashboardDrawer();
    syncDashboardUserLabel();
    loadDashboardTodayTasks();
    loadDashboardSummary();
    startDashboardAutoRefresh();

    const recFilter = document.getElementById('dashboard-rec-style-filter');
    if (recFilter) {
      recFilter.addEventListener('change', function () {
        if (dashboardState.summary) {
          renderRecommendations(dashboardState.summary);
        } else {
          loadDashboardSummary();
        }
      });
    }

    window.addEventListener('knowledge:updated', function () {
      loadDashboardTodayTasks();
      loadDashboardSummary();
    });

    window.addEventListener('focus', function () {
      loadDashboardSummary();
      renderLiveStayMinutes();
    });

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) return;
      loadDashboardSummary();
      renderLiveStayMinutes();
    });

    if (window.UserContext) {
      window.UserContext.onChange(function () {
        syncDashboardUserLabel();
        loadDashboardTodayTasks();
        loadDashboardSummary();
      });
    }
  });
})();
