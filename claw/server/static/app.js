// === WebSocket 连接 ===
let ws = null;
let wsReconnectTimer = null;

function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
        setStatus('ready', '就绪');
        if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
    };

    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        handleWSMessage(msg);
    };

    ws.onclose = () => {
        setStatus('error', '断开');
        wsReconnectTimer = setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
        setStatus('error', '错误');
    };
}

function setStatus(state, text) {
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    dot.className = 'status-dot' + (state === 'thinking' ? ' thinking' : state === 'error' ? ' error' : '');
    txt.textContent = text;
}

// === 消息处理 ===
function handleWSMessage(msg) {
    switch (msg.type) {
        case 'status':
            if (msg.step === 'start') { setStatus('thinking', '分析中...'); }
            addProgress(msg.message);
            break;
        case 'result':
            switch (msg.step) {
                case 'agent1':
                    renderEmotion(msg.data);
                    setPanelStatus('emotionStatus', 'done', '完成');
                    break;
                case 'agent2':
                    renderBreakpoint(msg.data);
                    setPanelStatus('breakpointStatus', 'done', '完成');
                    break;
                case 'agent2_5':
                    renderScout(msg.data);
                    setPanelStatus('scoutStatus', 'done', '完成');
                    break;
                case 'agent3':
                    addAIMessage(msg.data);
                    break;
            }
            break;
        case 'done':
            setStatus('ready', '就绪');
            if (msg.timing) {
                renderTiming(msg.timing);
                setPanelStatus('timingStatus', 'done', '完成');
            }
            removeProgress();
            break;
        case 'error':
            setStatus('error', '错误');
            addAIMessage('错误: ' + msg.message, true);
            removeProgress();
            break;
    }
}

// === 聊天消息 ===
function addMessage(role, text, isError) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'message ' + role + (isError ? ' error' : '');
    div.innerHTML = '<div class="avatar">' + (role === 'user' ? 'U' : 'AI') + '</div><div class="bubble">' + escapeHtml(text) + '</div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
}

function addAIMessage(data, isError) {
    let text = '';
    if (isError) {
        text = data;
    } else if (data && typeof data === 'object') {
        if (data.content) text = data.content;
        else if (data.error) text = '错误: ' + data.error;
        else text = JSON.stringify(data, null, 2);
    } else if (typeof data === 'string') {
        text = data;
    }
    addMessage('ai', text, isError);
}

function addProgress(text) {
    removeProgress();
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'message progress';
    div.id = 'progressMsg';
    div.innerHTML = '<div class="bubble"><span class="spinner"></span>' + escapeHtml(text) + '</div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function removeProgress() {
    const el = document.getElementById('progressMsg');
    if (el) el.remove();
}

function sendMessage() {
    const input = document.getElementById('userInput');
    const text = input.value.trim();
    if (!text) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    addMessage('user', text);
    input.value = '';
    setStatus('thinking', '思考中...');
    setPanelStatus('emotionStatus', 'running', '分析中');
    setPanelStatus('breakpointStatus', 'running', '分析中');
    setPanelStatus('scoutStatus', 'running', '等待中');
    setPanelStatus('timingStatus', '', '等待');

    ws.send(JSON.stringify({ type: 'message', content: text }));
}

document.getElementById('userInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// === 面板切换 ===
function togglePanel(bodyId) {
    const body = document.getElementById(bodyId);
    const card = body.parentElement;
    card.classList.toggle('collapsed');
}

function setPanelStatus(statusId, cls, text) {
    const el = document.getElementById(statusId);
    if (!el) return;
    el.className = 'panel-status' + (cls ? ' ' + cls : '');
    el.textContent = text;
}

// === HTML 转义 ===
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// === 辅助：解析 JSON ===
function parseJSON(data) {
    if (!data) return null;
    if (typeof data === 'object') return data;
    if (typeof data === 'string') {
        try { return JSON.parse(data); } catch(e) { return null; }
    }
    return null;
}

function extractJSON(data) {
    if (!data) return null;
    // 已经是纯对象且包含预期字段，直接返回
    if (typeof data === 'object' && !Array.isArray(data)) {
        // 如果对象有 action/teach_what 等字段，说明已经是解析好的 scout 数据
        if (data.action !== undefined || data.teach_what !== undefined || data.how !== undefined) {
            return data;
        }
        // 如果对象有 diagnosis 字段，说明已经是解析好的断点数据
        if (data.diagnosis !== undefined) return data;
        // 如果对象有 strengths 字段，说明已经是解析好的优势数据
        if (data.strengths !== undefined) return data;
        // 如果对象有 knowledge_flow 字段，说明已经是解析好的知识流数据
        if (data.knowledge_flow !== undefined) return data;
        // 如果有 content 字段且是字符串，尝试解析
        if (data.content && typeof data.content === 'string') {
            var c = data.content.trim();
            c = c.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '');
            var inner = parseJSON(c);
            if (inner) return inner;
        }
        // 有 error 字段，返回 null
        if (data.error) return null;
        // 其他情况返回原对象
        return data;
    }
    if (typeof data === 'string') {
        try { return JSON.parse(data); } catch(e) { return null; }
    }
    return null;
}

// ========== 情绪指纹渲染 ==========
function renderEmotion(data) {
    var body = document.getElementById('emotionBody');
    var parsed = extractJSON(data);
    if (!parsed) {
        body.innerHTML = '<div class="placeholder">解析失败</div>';
        return;
    }

    var html = '';

    // 认知状态
    var state = parsed.state;
    if (state) {
        var stateLabels = {
            'advancing': '推进中', 'exploring': '探索中', 'stalled': '停滞中',
            'skipping': '跳过中', 'flowing': '心流中'
        };
        var stateColors = {
            'advancing': '#10b981', 'exploring': '#3b82f6', 'stalled': '#f59e0b',
            'skipping': '#6b7280', 'flowing': '#a855f7'
        };
        html += '<div class="section-title">认知状态</div><div class="emotion-bars">';
        var stateKeys = ['advancing', 'exploring', 'stalled', 'skipping', 'flowing'];
        for (var i = 0; i < stateKeys.length; i++) {
            var k = stateKeys[i];
            var v = state[k] || 0;
            var pct = Math.min(v / 5 * 100, 100);
            html += '<div class="emotion-row"><span class="label">' + escapeHtml(stateLabels[k] || k) + '</span><div class="bar-track"><div class="bar-fill" style="width:' + pct + '%;background:' + stateColors[k] + '"></div></div><span class="value">' + v + '</span></div>';
        }
        html += '</div>';
    }

    // 情绪反应
    var emotion = parsed.emotion;
    if (emotion) {
        var emotionLabels = {
            'calm': '平静', 'confused': '困惑', 'frustrated': '挫败',
            'annoyed': '烦躁', 'anxious': '焦虑', 'confident': '自信'
        };
        var emotionColors = {
            'calm': '#10b981', 'confused': '#f59e0b', 'frustrated': '#ef4444',
            'annoyed': '#f97316', 'anxious': '#8b5cf6', 'confident': '#3b82f6'
        };
        var subMap = {
            'confused': { key: 'confused_sub', labels: { 'curious': '好奇探索', 'blocked': '卡住反复', 'lost': '停下等待', 'stall': '原因不明' } },
            'frustrated': { key: 'frustrated_sub', labels: { 'anger_at_ai': '攻击AI', 'self_sad': '否定自己', 'numb': '麻木' } },
            'annoyed': { key: 'annoyed_sub', labels: { 'wrong_method': '嫌讲法不对', 'unclear_explanation': '嫌讲不清楚', 'too_slow': '嫌节奏慢', 'bad_state': '状态差', 'restless': '焦躁', 'unclear': '原因不明' } },
            'anxious': { key: 'anxious_sub', labels: { 'rushing': '赶时间', 'doubt_direction': '质疑目标', 'doubt_self': '质疑自己', 'restless': '坐不住' } },
            'confident': { key: 'confident_sub', labels: { 'confirming': '主动确认', 'advancing': '毫不犹豫推进' } }
        };

        html += '<div class="section-title">情绪反应</div><div class="emotion-bars">';
        var emoKeys = ['calm', 'confused', 'frustrated', 'annoyed', 'anxious', 'confident'];
        for (var i = 0; i < emoKeys.length; i++) {
            var k = emoKeys[i];
            var v = emotion[k] || 0;
            var pct = Math.min(v / 5 * 100, 100);
            html += '<div class="emotion-row"><span class="label">' + escapeHtml(emotionLabels[k] || k) + '</span><div class="bar-track"><div class="bar-fill" style="width:' + pct + '%;background:' + emotionColors[k] + '"></div></div><span class="value">' + v + '</span></div>';

            // 子类展开
            if (v > 0) {
                var subInfo = subMap[k];
                if (subInfo) {
                    var subData = parsed[subInfo.key];
                    if (subData) {
                        var subHtml = '';
                        var subKeys = Object.keys(subData);
                        for (var j = 0; j < subKeys.length; j++) {
                            var sk = subKeys[j];
                            if (sk === 'quote') continue;
                            var sv = subData[sk] || 0;
                            if (sv <= 0) continue;
                            var slabel = (subInfo.labels && subInfo.labels[sk]) ? subInfo.labels[sk] : sk;
                            subHtml += '<div class="emotion-row"><span class="label sub-label">' + slabel + '</span><div class="bar-track"><div class="bar-fill" style="width:' + Math.min(sv / 5 * 100, 100) + '%;background:' + emotionColors[k] + '88"></div></div><span class="value">' + sv + '</span></div>';
                        }
                        var quote = subData.quote || '';
                        if (subHtml) {
                            html += '<div class="sub-emotion"><div class="sub-emotion-title">子类</div><div class="emotion-bars sub-bars">' + subHtml + '</div>';
                            if (quote) html += '<div class="sub-quote">' + escapeHtml(quote) + '</div>';
                            html += '</div>';
                        }
                    }
                }
            }
        }
        html += '</div>';
    }

    // 信任信号
    var trust = parsed.trust_signal;
    if (trust !== undefined) {
        var trustPct = Math.round(trust * 100);
        var trustColor = trust >= 0.7 ? '#10b981' : trust >= 0.5 ? '#f59e0b' : trust >= 0.3 ? '#f97316' : '#ef4444';
        html += '<div class="section-title">信任信号</div>';
        html += '<div class="emotion-row"><span class="label">信任度</span><div class="bar-track"><div class="bar-fill" style="width:' + trustPct + '%;background:' + trustColor + '"></div></div><span class="value trust-value">' + trust.toFixed(1) + '</span></div>';
    }

    body.innerHTML = html || '<div class="placeholder">无情绪数据</div>';
}

// ========== 断点诊断渲染 ==========
function renderBreakpoint(data) {
    var body = document.getElementById('breakpointBody');
    if (!data || typeof data !== 'object') {
        body.innerHTML = '<div class="placeholder">无数据</div>';
        return;
    }

    var html = '';
    var diagData = extractJSON(data.diagnosis);
    if (diagData && diagData.diagnosis) {
        html += renderDiagnosisCards(diagData.diagnosis);
    }
    var strengthsData = extractJSON(data.strengths);
    if (strengthsData && strengthsData.strengths) {
        html += renderStrengthsCards(strengthsData.strengths);
    }
    var flowData = extractJSON(data.knowledge_flow);
    if (flowData && flowData.knowledge_flow) {
        html += renderKnowledgeFlow(flowData.knowledge_flow);
    }
    body.innerHTML = html || '<div class="placeholder">无诊断数据</div>';
}

function renderDiagnosisCards(diag) {
    var typeColors = {
        '情绪阻断': '#ef4444',
        '认知过载': '#f59e0b',
        '前置缺失': '#3b82f6',
        '讲法不对口': '#a855f7',
        '多义混淆': '#ec4899',
        '假性掌握': '#f97316',
        '无断点': '#10b981'
    };

    var html = '';

    function renderCard(prefix, bp) {
        if (!bp || bp.type === '无断点') return '';
        var color = typeColors[bp.type] || '#6b7086';
        var confPct = bp.confidence ? Math.round(bp.confidence * 100) : 0;
        return '<div class="bp-card ' + (prefix === 'primary' ? 'primary' : 'secondary') + '"><div class="bp-card-header"><span class="bp-type-badge" style="background:' + color + '20;color:' + color + ';border:1px solid ' + color + '40">' + escapeHtml(bp.type || '') + (bp.subtype ? ' \u00b7 ' + escapeHtml(bp.subtype) : '') + '</span><span class="bp-confidence" style="color:' + color + '">' + confPct + '%</span></div><div class="bp-card-body"><div class="bp-field"><span class="bp-field-label">断点对象</span><span class="bp-field-value concept">' + escapeHtml(bp.concept || '\u2014') + '</span></div></div></div>';
    }

    var primary = diag.primary;
    var secondary = diag.secondary;
    var overlap = diag.overlap;

    if (primary && primary.type !== '无断点') {
        html += '<div class="section-title">主诊断</div>';
        html += renderCard('primary', primary);
    }
    if (secondary && secondary.type) {
        html += '<div class="section-title">次诊断</div>';
        html += renderCard('secondary', secondary);
    }
    if (overlap && overlap.relation) {
        html += '<div class="overlap-badge"><span class="overlap-label">关联</span><span class="overlap-rel">' + escapeHtml(overlap.relation) + '</span><span class="overlap-detail">' + escapeHtml(overlap.detail || '') + '</span></div>';
    }
    if (!html) html = '<div class="placeholder">无断点 — 正常推进</div>';
    return html;
}

function renderStrengthsCards(strengths) {
    var sections = [
        { key: 'confirmed_concepts', icon: '\u2705', label: '已确认掌握', color: '#10b981', field: 'concept' },
        { key: 'effective_approaches', icon: '\u2B50', label: '有效学习方式', color: '#3b82f6', field: 'approach' },
        { key: 'stable_behaviors', icon: '\uD83D\uDCA1', label: '稳定学习行为', color: '#a855f7', field: 'behavior' }
    ];

    var html = '';
    for (var i = 0; i < sections.length; i++) {
        var sec = sections[i];
        var items = strengths[sec.key];
        if (!items || !Array.isArray(items) || items.length === 0) continue;
        html += '<div class="strength-section"><div class="strength-sec-header" style="color:' + sec.color + '">' + sec.icon + ' ' + sec.label + '</div>';
        for (var j = 0; j < items.length; j++) {
            var item = items[j];
            var name = item[sec.field] || '';
            var evidence = item.evidence || '';
            html += '<div class="strength-item"><div class="strength-name" style="border-left:3px solid ' + sec.color + '">' + escapeHtml(name) + '</div>';
            if (evidence) html += '<div class="strength-evidence">"' + escapeHtml(evidence) + '"</div>';
            html += '</div>';
        }
        html += '</div>';
    }
    return html;
}

function renderKnowledgeFlow(flow) {
    var nodes = flow;
    if (!nodes || !Array.isArray(nodes) || nodes.length === 0) {
        return '<div class="section-title">知识流</div><div class="placeholder">无知识流数据</div>';
    }

    var stateLabels = { '通': '通', '偏': '偏', '卡': '卡', '跳': '跳', '悬置': '悬置', '崩': '崩' };
    var stateColors = { '通': '#10b981', '偏': '#f59e0b', '卡': '#ef4444', '跳': '#3b82f6', '悬置': '#6b7280', '崩': '#dc2626' };
    var transSymbols = { '\u2192': '\u2794', '\u2193': '\u2B07', '\u2715': '\u2715', '\u2190': '\u2B05', '\u2197': '\u2197' };

    var html = '<div class="section-title">知识流</div><div class="flow-container">';
    for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];
        var state = node.user_state || '';
        var stateLabel = stateLabels[state] || state;
        var stateColor = stateColors[state] || '#6b7280';

        html += '<div class="flow-node"><div class="flow-node-header"><span class="flow-node-id">#' + (node.node_id || i + 1) + '</span><span class="flow-node-concept">' + escapeHtml(node.concept || '') + '</span><span class="flow-state-badge" style="background:' + stateColor + '20;color:' + stateColor + ';border:1px solid ' + stateColor + '40">' + stateLabel + '</span></div><div class="flow-node-evidence">' + escapeHtml(node.evidence || '') + '</div></div>';

        if (i < nodes.length - 1) {
            var trans = node.transition || '';
            var sym = transSymbols[trans] || trans;
            html += '<div class="flow-arrow">' + sym + '</div>';
        }
    }
    html += '</div>';
    return html;
}

// ========== 认知侦察渲染 ==========
function renderScout(data) {
    var body = document.getElementById('scoutBody');
    var parsed = extractJSON(data);
    if (!parsed) {
        var content = data && data.content ? data.content : (typeof data === 'string' ? data : '');
        if (content) {
            body.innerHTML = '<div class="scout-main-card"><div class="placeholder">' + escapeHtml(content) + '</div></div>';
            return;
        }
        body.innerHTML = '<div class="placeholder">解析失败</div>';
        return;
    }

    var actionColors = {
        '讲': '#3b82f6', '练': '#10b981', '验': '#f59e0b', '补': '#a855f7',
        '纠': '#ef4444', '挑': '#f97316', '休息': '#6b7280'
    };
    var stanceColors = {
        '正常推进': '#3b82f6', '退阶补缺': '#f59e0b', '承接情绪后推进': '#a855f7',
        '跟随探索': '#10b981', '对抗挑战': '#ef4444', '暂停降负': '#6b7280'
    };

    var action = parsed.action || '';
    var actionColor = actionColors[action] || '#6b7280';
    var stance = parsed.stance || '';
    var stanceColor = stanceColors[stance] || '#6b7280';

    var html = '<div class="scout-cards">';
    html += '<div class="scout-main-card"><div class="scout-action-row"><span class="scout-action-badge" style="background:' + actionColor + '20;color:' + actionColor + '">' + escapeHtml(action) + '</span><span class="scout-stance" style="color:' + stanceColor + '">' + escapeHtml(stance) + '</span></div>';

    if (parsed.teach_what) {
        html += '<div class="scout-field"><span class="scout-field-label">教什么</span><span class="scout-field-value">' + escapeHtml(parsed.teach_what) + '</span></div>';
    }
    if (parsed.how) {
        html += '<div class="scout-field"><span class="scout-field-label">怎么教</span><span class="scout-field-value">' + escapeHtml(parsed.how) + '</span></div>';
    }
    html += '</div>';

    if (parsed.insight) {
        html += '<div class="scout-insight-card"><div class="scout-insight-label">侦察洞察</div><div class="scout-insight-content">' + escapeHtml(parsed.insight) + '</div></div>';
    }

    html += '</div>';
    body.innerHTML = html;
}

// ========== 耗时渲染 ==========
function renderTiming(timing) {
    var body = document.getElementById('timingBody');
    body.innerHTML = '<div class="timing-row"><span>Agent1+2</span><span>' + (timing.step1 || '?') + 's</span></div><div class="timing-row"><span>总计</span><span>' + (timing.total || '?') + 's</span></div>';
}

// ========== 学习画像渲染 ==========
function renderProfile(profile) {
    var body = document.getElementById('profileBody');
    var status = document.getElementById('profileStatus');
    if (!profile) {
        body.innerHTML = '<span class="placeholder">未生成画像，请先完成画像测试</span>';
        status.textContent = '';
        status.className = 'panel-status';
        return;
    }

    status.textContent = '已加载';
    status.className = 'panel-status done';

    var categories = [
        { key: 'learning_style', label: '学习风格', icon: '\uD83D\uDCD6', dims: [
            { key: 'demand', label: '需求驱动', cls: 'demand' },
            { key: 'practice', label: '实践驱动', cls: 'practice' },
            { key: 'structure', label: '结构驱动', cls: 'structure' },
            { key: 'analogy', label: '类比驱动', cls: 'analogy' }
        ]},
        { key: 'obstacle_response', label: '障碍响应', icon: '\uD83E\uDDF1', dims: [
            { key: 'drill', label: '硬啃', cls: 'drill' },
            { key: 'reroute', label: '绕路', cls: 'reroute' },
            { key: 'diagnose', label: '诊断', cls: 'diagnose' }
        ]},
        { key: 'consolidation', label: '巩固方式', icon: '\uD83D\uDD28', dims: [
            { key: 'cement', label: '固化', cls: 'cement' },
            { key: 'rebuild', label: '重建', cls: 'rebuild' },
            { key: 'surface', label: '表层', cls: 'surface' }
        ]},
        { key: 'initiative', label: '主动性', icon: '\uD83D\uDE80', dims: [
            { key: 'self_driven', label: '自驱', cls: 'self_driven' },
            { key: 'collaborative', label: '协作', cls: 'collaborative' },
            { key: 'external', label: '外部驱动', cls: 'external' }
        ]},
        { key: 'stress_tolerance', label: '压力耐受', icon: '\uD83D\uDCAA', dims: [
            { key: 'stress_high', label: '高耐受', cls: 'stress_high' },
            { key: 'stress_low', label: '低耐受', cls: 'stress_low' }
        ]}
    ];

    var html = '';
    for (var i = 0; i < categories.length; i++) {
        var cat = categories[i];
        var catDims = profile[cat.key];
        if (!catDims || typeof catDims !== 'object') continue;

        html += '<div class="profile-category"><div class="profile-cat-label"><span class="cat-icon">' + cat.icon + '</span>' + cat.label + '</div>';

        for (var j = 0; j < cat.dims.length; j++) {
            var dim = cat.dims[j];
            var val = catDims[dim.key];
            if (val === undefined) continue;
            var pct = Math.round(val * 100);
            html += '<div class="profile-bar-wrap"><div class="profile-bar-label"><span>' + dim.label + '</span><span>' + pct + '%</span></div><div class="profile-bar-track"><div class="profile-bar-fill ' + dim.cls + '" style="width:' + pct + '%"></div></div></div>';
        }
        html += '</div>';
    }

    if (profile.risks && Array.isArray(profile.risks) && profile.risks.length > 0) {
        html += '<div class="profile-risks"><div class="profile-risks-label">风险提示</div>';
        for (var k = 0; k < profile.risks.length; k++) {
            html += '<span class="profile-risk-tag">' + escapeHtml(profile.risks[k]) + '</span>';
        }
        html += '</div>';
    }

    body.innerHTML = html || '<span class="placeholder">画像数据为空</span>';
}

// ========== 画像测试 Modal ==========
var onboardingAnswers = {};
var onboardingQuestions = [];

function openOnboarding() {
    document.getElementById('onboardingModal').style.display = 'flex';
    document.getElementById('onboardingTopic').style.display = 'block';
    document.getElementById('onboardingQuestions').style.display = 'none';
    document.getElementById('onboardingFooter').style.display = 'none';
    document.getElementById('onboardingTopicInput').value = '';
    document.getElementById('onboardingTitle').textContent = '学习画像测试';
    onboardingAnswers = {};
    onboardingQuestions = [];
}

function closeOnboarding() {
    document.getElementById('onboardingModal').style.display = 'none';
}

async function startOnboarding() {
    var topic = document.getElementById('onboardingTopicInput').value.trim();
    if (!topic) return;

    document.getElementById('onboardingTopic').style.display = 'none';
    var qDiv = document.getElementById('onboardingQuestions');
    qDiv.style.display = 'block';
    qDiv.innerHTML = '<div class="onboarding-loading"><span class="spinner"></span><span>正在生成诊断题...</span></div>';

    try {
        var resp = await fetch('/api/onboarding/questions?topic=' + encodeURIComponent(topic));
        var data = await resp.json();

        if (data.error) {
            qDiv.innerHTML = '<div class="onboarding-result error">错误: ' + escapeHtml(data.error) + '</div>';
            return;
        }

        var questions = data.questions;
        if (!questions && data.questions_raw) {
            qDiv.innerHTML = '<div class="onboarding-raw">' + escapeHtml(data.questions_raw) + '</div>';
            return;
        }

        if (!questions || !Array.isArray(questions)) {
            qDiv.innerHTML = '<div class="onboarding-result error">题目格式异常</div>';
            return;
        }

        onboardingQuestions = questions;
        renderQuestions(questions);
        document.getElementById('onboardingFooter').style.display = 'flex';
    } catch (e) {
        qDiv.innerHTML = '<div class="onboarding-result error">请求失败: ' + escapeHtml(e.message) + '</div>';
    }
}

function renderQuestions(questions) {
    var qDiv = document.getElementById('onboardingQuestions');
    var html = '';
    var labels = ['A', 'B', 'C', 'D'];
    for (var i = 0; i < questions.length; i++) {
        var q = questions[i];
        var qid = 'q' + (i + 1);
        html += '<div class="onboarding-q" id="oq_' + qid + '"><div class="onboarding-q-num">第 ' + (i + 1) + ' 题</div><div class="onboarding-q-text">' + escapeHtml(q.text || q.question || '') + '</div><div class="onboarding-q-options">';
        var opts = q.options || {};
        for (var j = 0; j < labels.length; j++) {
            var letter = labels[j];
            var optText = opts[letter];
            if (!optText) continue;
            html += '<label class="onboarding-opt"><input type="radio" name="' + qid + '" value="' + letter + '" onchange="selectAnswer(\'' + qid + '\', \'' + letter + '\')">' + letter + '. ' + escapeHtml(optText) + '</label>';
        }
        html += '</div></div>';
    }
    qDiv.innerHTML = html;
}

function selectAnswer(qid, choice) {
    onboardingAnswers[qid] = choice;
    var el = document.getElementById('oq_' + qid);
    if (el) el.classList.remove('unanswered');
}

async function submitOnboarding() {
    var total = onboardingQuestions.length;
    if (Object.keys(onboardingAnswers).length < total) {
        for (var i = 0; i < total; i++) {
            var qid = 'q' + (i + 1);
            if (!onboardingAnswers[qid]) {
                var el = document.getElementById('oq_' + qid);
                if (el) el.classList.add('unanswered');
            }
        }
        return;
    }

    var submitBtn = document.getElementById('onboardingSubmit');
    submitBtn.disabled = true;
    submitBtn.textContent = '提交中...';

    try {
        var resp = await fetch('/api/onboarding/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ answers: onboardingAnswers })
        });
        var data = await resp.json();

        var qDiv = document.getElementById('onboardingQuestions');
        if (data.error) {
            qDiv.innerHTML = '<div class="onboarding-result error">' + escapeHtml(data.error) + '</div>';
            return;
        }

        document.getElementById('onboardingFooter').style.display = 'none';
        document.getElementById('onboardingTitle').textContent = '画像测试完成';

        var resultHtml = '<div class="onboarding-result"><div class="onboarding-result-icon">\uD83E\uDDE0</div><h3>学习画像已生成</h3>';
        if (data.narrative) {
            resultHtml += '<div class="onboarding-result-text">' + escapeHtml(data.narrative) + '</div>';
        }
        resultHtml += '<button class="btn btn-primary" onclick="closeOnboarding()">返回教学</button></div>';
        qDiv.innerHTML = resultHtml;

        if (data.profile) {
            renderProfile(data.profile);
        }
        loadProfile();
    } catch (e) {
        document.getElementById('onboardingQuestions').innerHTML = '<div class="onboarding-result error">提交失败: ' + escapeHtml(e.message) + '</div>';
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '提交';
    }
}

// ========== 知识库 Modal ==========
function openKB() {
    document.getElementById('kbModal').style.display = 'flex';
    loadKBFiles();
}

function closeKB() {
    document.getElementById('kbModal').style.display = 'none';
}

async function loadKBFiles() {
    var list = document.getElementById('kbFileList');
    list.innerHTML = '<div class="placeholder">加载中...</div>';
    try {
        var resp = await fetch('/api/knowledge/files');
        var data = await resp.json();
        if (data.files && data.files.length > 0) {
            var html = '';
            for (var i = 0; i < data.files.length; i++) {
                var f = data.files[i];
                html += '<div class="kb-file-item"><span class="kb-file-icon">\uD83D\uDCC4</span><span class="kb-file-name">' + escapeHtml(f.name) + '</span><span class="kb-file-size">' + escapeHtml(f.size_human) + '</span><button class="kb-file-delete" onclick="deleteKBFile(\'' + escapeHtml(f.name).replace(/'/g, "\\'") + '\')">\u2715</button></div>';
            }
            list.innerHTML = html;
        } else {
            list.innerHTML = '<div class="placeholder">暂无文件</div>';
        }
    } catch (e) {
        list.innerHTML = '<div class="placeholder">加载失败: ' + escapeHtml(e.message) + '</div>';
    }
}

async function uploadKBFile(file) {
    if (!file) return;
    var formData = new FormData();
    formData.append('file', file);
    try {
        var resp = await fetch('/api/knowledge/upload', { method: 'POST', body: formData });
        var data = await resp.json();
        if (data.error) {
            alert('上传失败: ' + data.error);
        } else {
            loadKBFiles();
        }
    } catch (e) {
        alert('上传失败: ' + e.message);
    }
    document.getElementById('kbFileInput').value = '';
}

async function deleteKBFile(name) {
    try {
        await fetch('/api/knowledge/files/' + encodeURIComponent(name), { method: 'DELETE' });
        loadKBFiles();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // 画像测试按钮
    var onboardingBtn = document.getElementById('onboardingBtn');
    if (onboardingBtn) {
        onboardingBtn.addEventListener('click', openOnboarding);
    }
    // 知识库按钮
    var kbBtn = document.getElementById('kbBtn');
    if (kbBtn) {
        kbBtn.addEventListener('click', openKB);
    }
    // 知识库拖拽上传
    var dropZone = document.getElementById('kbDropZone');
    var fileInput = document.getElementById('kbFileInput');

    if (dropZone) {
        dropZone.addEventListener('click', function() { fileInput.click(); });
        dropZone.addEventListener('dragover', function(e) { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', function() { dropZone.classList.remove('dragover'); });
        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) uploadKBFile(e.dataTransfer.files[0]);
        });
    }
});

// ========== 加载画像 ==========
async function loadProfile() {
    try {
        var resp = await fetch('/api/profile');
        var data = await resp.json();
        if (data.profile) {
            renderProfile(data.profile);
        }
    } catch (e) {
        // 静默失败
    }
}

// ========== 初始化 ==========
connectWS();
loadProfile();