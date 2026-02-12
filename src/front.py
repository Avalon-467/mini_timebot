from flask import Flask, render_template_string, request, jsonify, session, Response
import requests
import os
from dotenv import load_dotenv

# 加载 .env 配置
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
load_dotenv(dotenv_path=os.path.join(root_dir, "config", ".env"))

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- 配置区 ---
PORT_AGENT = int(os.getenv("PORT_AGENT", "51200"))
LOCAL_AGENT_URL = f"http://127.0.0.1:{PORT_AGENT}/ask"
LOCAL_AGENT_STREAM_URL = f"http://127.0.0.1:{PORT_AGENT}/ask_stream"
LOCAL_AGENT_CANCEL_URL = f"http://127.0.0.1:{PORT_AGENT}/cancel"
LOCAL_LOGIN_URL = f"http://127.0.0.1:{PORT_AGENT}/login"
LOCAL_TOOLS_URL = f"http://127.0.0.1:{PORT_AGENT}/tools"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Xavier AnyControl | AI Agent</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.2/marked.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>

    <style>
        .chat-container { height: calc(100vh - 180px); }
        .markdown-body pre { background: #1e1e1e; padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; overflow-x: auto; }
        .markdown-body code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.9em; }
        .message-user { border-radius: 1.25rem 1.25rem 0.2rem 1.25rem; }
        .message-agent { border-radius: 1.25rem 1.25rem 1.25rem 0.2rem; }
        .dot { width: 6px; height: 6px; background: #3b82f6; border-radius: 50%; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 0.3; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1.2); } }
        /* Tool panel styles */
        .tool-panel { transition: max-height 0.3s ease, opacity 0.3s ease; overflow: hidden; }
        .tool-panel.collapsed { max-height: 0; opacity: 0; }
        .tool-panel.expanded { max-height: 300px; opacity: 1; overflow-y: auto; }
        .tool-tag { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 9999px; font-size: 12px; cursor: pointer; user-select: none; transition: all 0.25s ease; }
        .tool-tag.enabled { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
        .tool-tag.enabled:hover { background: #dbeafe; }
        .tool-tag.disabled { background: #f3f4f6; color: #9ca3af; border: 1px solid #e5e7eb; opacity: 0.65; }
        .tool-tag.disabled:hover { background: #e5e7eb; opacity: 0.8; }
        .tool-toggle-btn { cursor: pointer; user-select: none; transition: color 0.2s; }
        .tool-toggle-btn:hover { color: #2563eb; }
        .tool-toggle-icon { display: inline-block; transition: transform 0.3s ease; }
        .tool-toggle-icon.open { transform: rotate(180deg); }
    </style>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal">

    <!-- ========== 登录页 ========== -->
    <div id="login-screen" class="min-h-screen flex items-center justify-center">
        <div class="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md border">
            <div class="flex items-center justify-center space-x-3 mb-6">
                <div class="bg-blue-600 p-3 rounded-xl text-white font-bold text-2xl">X</div>
                <h1 class="text-2xl font-bold text-gray-800">Xavier AnyControl</h1>
            </div>
            <p class="text-center text-gray-500 text-sm mb-8">请登录以开始对话</p>
            <div class="space-y-4">
                <input id="username-input" type="text" maxlength="32"
                    class="w-full p-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 text-center text-lg"
                    placeholder="用户名" autofocus>
                <input id="password-input" type="password" maxlength="64"
                    class="w-full p-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 text-center text-lg"
                    placeholder="密码">
                <div id="login-error" class="text-red-500 text-sm text-center hidden"></div>
                <button onclick="handleLogin()" id="login-btn"
                    class="w-full bg-blue-600 hover:bg-blue-700 text-white py-3 rounded-xl font-bold text-lg transition-all shadow-lg">
                    登录
                </button>
            </div>
            <p class="text-xs text-gray-400 text-center mt-6">身份验证后方可使用，对话和文件按用户隔离</p>
        </div>
    </div>

    <!-- ========== 聊天页（初始隐藏） ========== -->
    <div id="chat-screen" class="max-w-4xl mx-auto h-screen flex-col shadow-2xl bg-white border-x border-gray-200" style="display:none;">
        <header class="p-4 border-b bg-white flex justify-between items-center sticky top-0 z-10">
            <div class="flex items-center space-x-3">
                <div class="bg-blue-600 p-2 rounded-lg text-white font-bold text-xl">X</div>
                <div>
                    <h1 class="text-lg font-bold text-gray-800 leading-tight">Xavier AnyControl</h1>
                    <p class="text-xs text-green-500 flex items-center">● 链路已加密 (HTTPS)</p>
                </div>
            </div>
            <div class="flex items-center space-x-2">
                <div id="uid-display" class="text-sm font-mono bg-gray-100 px-3 py-1 rounded border"></div>
                <button onclick="handleLogout()" class="text-xs text-gray-400 hover:text-red-500 px-2 py-1 rounded transition-colors" title="切换用户">退出</button>
            </div>
        </header>

        <div id="chat-box" class="chat-container overflow-y-auto p-6 space-y-6 flex-grow bg-gray-50">
            <div class="flex justify-start">
                <div class="message-agent bg-white border p-4 max-w-[85%] shadow-sm text-gray-700">
                    你好！我是 Xavier 智能助手。我已经准备好为你服务，请输入你的指令。
                </div>
            </div>
        </div>

        <div class="p-4 border-t bg-white">
            <!-- Tool List Panel -->
            <div id="tool-panel-wrapper" class="mb-2" style="display:none;">
                <div class="flex items-center justify-between mb-1">
                    <div class="tool-toggle-btn flex items-center space-x-1 text-sm text-gray-500 font-medium" onclick="toggleToolPanel()">
                        <span>🧰 可用工具</span>
                        <span id="tool-count" class="text-xs text-gray-400"></span>
                        <span id="tool-toggle-icon" class="tool-toggle-icon text-xs">▼</span>
                    </div>
                </div>
                <div id="tool-panel" class="tool-panel collapsed">
                    <div id="tool-list" class="flex flex-wrap gap-2 p-2 bg-gray-50 rounded-xl border border-gray-200">
                        <!-- tools will be injected here -->
                    </div>
                </div>
            </div>
            <div class="flex items-end space-x-3">
                <div class="flex-grow">
                    <textarea id="user-input" rows="1" 
                        class="w-full p-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none transition-all"
                        placeholder="输入指令，Shift + Enter 换行..."></textarea>
                </div>
                <button onclick="handleSend()" id="send-btn"
                    class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl transition-all font-bold shadow-lg h-[50px]">
                    发送
                </button>
                <button onclick="handleCancel()" id="cancel-btn"
                    class="bg-red-500 hover:bg-red-600 text-white px-6 py-3 rounded-xl transition-all font-bold shadow-lg h-[50px]"
                    style="display:none;">
                    终止
                </button>
            </div>
            <p class="text-[10px] text-center text-gray-400 mt-3 font-mono">Secured by Nginx Reverse Proxy & SSH Tunnel</p>
        </div>
    </div>

    <script>
        marked.setOptions({
            highlight: function(code, lang) {
                const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                return hljs.highlight(code, { language }).value;
            },
            langPrefix: 'hljs language-'
        });

        let currentUserId = null;
        let currentAbortController = null; // 用于终止流式请求

        // ===== 登录逻辑 =====
        async function handleLogin() {
            const nameInput = document.getElementById('username-input');
            const pwInput = document.getElementById('password-input');
            const errorDiv = document.getElementById('login-error');
            const loginBtn = document.getElementById('login-btn');
            const name = nameInput.value.trim();
            const password = pwInput.value;

            errorDiv.classList.add('hidden');

            if (!name) { nameInput.focus(); return; }
            if (!password) { pwInput.focus(); return; }

            if (!/^[a-zA-Z0-9_\\-\\u4e00-\\u9fa5]+$/.test(name)) {
                errorDiv.textContent = '用户名只能包含字母、数字、下划线、短横线或中文';
                errorDiv.classList.remove('hidden');
                return;
            }

            loginBtn.disabled = true;
            loginBtn.textContent = '验证中...';

            try {
                const resp = await fetch("/proxy_login", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: name, password: password })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    errorDiv.textContent = data.detail || data.error || '登录失败';
                    errorDiv.classList.remove('hidden');
                    return;
                }

                currentUserId = name;
                // 不存储密码明文到 localStorage，存到 sessionStorage
                sessionStorage.setItem('userId', name);
                sessionStorage.setItem('authToken', data.token || '');

                document.getElementById('uid-display').textContent = 'UID: ' + name;
                document.getElementById('login-screen').style.display = 'none';
                document.getElementById('chat-screen').style.display = 'flex';
                document.getElementById('user-input').focus();
                loadTools(); // load tool list after login
            } catch (e) {
                errorDiv.textContent = '网络错误: ' + e.message;
                errorDiv.classList.remove('hidden');
            } finally {
                loginBtn.disabled = false;
                loginBtn.textContent = '登录';
            }
        }

        function handleLogout() {
            currentUserId = null;
            sessionStorage.removeItem('userId');
            sessionStorage.removeItem('authToken');
            fetch("/proxy_logout", { method: 'POST' });
            document.getElementById('chat-screen').style.display = 'none';
            document.getElementById('login-screen').style.display = 'flex';
            document.getElementById('username-input').value = '';
            document.getElementById('password-input').value = '';
            document.getElementById('login-error').classList.add('hidden');
            document.getElementById('username-input').focus();
            const chatBox = document.getElementById('chat-box');
            chatBox.innerHTML = `
                <div class="flex justify-start">
                    <div class="message-agent bg-white border p-4 max-w-[85%] shadow-sm text-gray-700">
                        你好！我是 Xavier 智能助手。我已经准备好为你服务，请输入你的指令。
                    </div>
                </div>`;
        }

        // ===== Tool Panel 逻辑 =====
        let toolPanelOpen = false;
        let allTools = [];       // [{name, description}]
        let enabledToolSet = new Set(); // 当前启用的工具名集合

        function toggleToolPanel() {
            const panel = document.getElementById('tool-panel');
            const icon = document.getElementById('tool-toggle-icon');
            toolPanelOpen = !toolPanelOpen;
            if (toolPanelOpen) {
                panel.classList.remove('collapsed');
                panel.classList.add('expanded');
                icon.classList.add('open');
            } else {
                panel.classList.remove('expanded');
                panel.classList.add('collapsed');
                icon.classList.remove('open');
            }
        }

        function updateToolCount() {
            const toolCount = document.getElementById('tool-count');
            toolCount.textContent = '(' + enabledToolSet.size + '/' + allTools.length + ')';
        }

        function toggleTool(name, tagEl) {
            if (enabledToolSet.has(name)) {
                enabledToolSet.delete(name);
                tagEl.classList.remove('enabled');
                tagEl.classList.add('disabled');
            } else {
                enabledToolSet.add(name);
                tagEl.classList.remove('disabled');
                tagEl.classList.add('enabled');
            }
            updateToolCount();
        }

        function getEnabledTools() {
            // If all tools enabled, return null (means "all")
            if (enabledToolSet.size === allTools.length) return null;
            return Array.from(enabledToolSet);
        }

        async function loadTools() {
            try {
                const resp = await fetch('/proxy_tools');
                if (!resp.ok) return;
                const data = await resp.json();
                const tools = data.tools || [];
                const toolList = document.getElementById('tool-list');
                const wrapper = document.getElementById('tool-panel-wrapper');

                if (tools.length === 0) {
                    wrapper.style.display = 'none';
                    return;
                }

                allTools = tools;
                enabledToolSet = new Set(tools.map(t => t.name)); // default: all enabled
                toolList.innerHTML = '';
                tools.forEach(t => {
                    const tag = document.createElement('span');
                    tag.className = 'tool-tag enabled';
                    tag.title = t.description || '';
                    tag.textContent = t.name;
                    tag.onclick = () => toggleTool(t.name, tag);
                    toolList.appendChild(tag);
                });
                updateToolCount();
                wrapper.style.display = 'block';
            } catch (e) {
                console.warn('Failed to load tools:', e);
            }
        }

        // 页面加载时检查 session（不自动登录，需要重新输入密码）
        (function checkSession() {
            const saved = sessionStorage.getItem('userId');
            if (saved) {
                // session 还在（同一标签页未关闭），恢复显示
                currentUserId = saved;
                document.getElementById('uid-display').textContent = 'UID: ' + saved;
                document.getElementById('login-screen').style.display = 'none';
                document.getElementById('chat-screen').style.display = 'flex';
                loadTools(); // restore tool list
            }
        })();

        // 登录输入框回车
        document.getElementById('username-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); document.getElementById('password-input').focus(); }
        });
        document.getElementById('password-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); handleLogin(); }
        });

        // ===== 聊天逻辑 =====
        const chatBox = document.getElementById('chat-box');
        const inputField = document.getElementById('user-input');
        const sendBtn = document.getElementById('send-btn');
        const cancelBtn = document.getElementById('cancel-btn');

        function setStreamingUI(streaming) {
            if (streaming) {
                sendBtn.style.display = 'none';
                cancelBtn.style.display = 'inline-block';
                inputField.disabled = true;
            } else {
                sendBtn.style.display = 'inline-block';
                cancelBtn.style.display = 'none';
                sendBtn.disabled = false;
                inputField.disabled = false;
            }
        }

        async function handleCancel() {
            // 1. 中断前端的 fetch 流读取
            if (currentAbortController) {
                currentAbortController.abort();
                currentAbortController = null;
            }
            // 2. 通知后端终止智能体
            try {
                await fetch("/proxy_cancel", { method: 'POST' });
            } catch(e) { /* 忽略 */ }
        }

        function appendMessage(content, isUser = false) {
            const wrapper = document.createElement('div');
            wrapper.className = `flex ${isUser ? 'justify-end' : 'justify-start'} animate-in fade-in duration-300`;
            const div = document.createElement('div');
            div.className = `p-4 max-w-[85%] shadow-sm ${isUser ? 'bg-blue-600 text-white message-user' : 'bg-white border text-gray-800 message-agent'}`;
            if (isUser) {
                div.innerText = content;
            } else {
                div.className += " markdown-body";
                div.innerHTML = marked.parse(content);
                div.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
            }
            wrapper.appendChild(div);
            chatBox.appendChild(wrapper);
            chatBox.scrollTop = chatBox.scrollHeight;
            return div;
        }

        function showTyping() {
            const wrapper = document.createElement('div');
            wrapper.id = 'typing-indicator';
            wrapper.className = 'flex justify-start';
            wrapper.innerHTML = `
                <div class="message-agent bg-white border p-4 flex space-x-2 items-center shadow-sm">
                    <div class="dot"></div><div class="dot"></div><div class="dot"></div>
                </div>`;
            chatBox.appendChild(wrapper);
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        async function handleSend() {
            const text = inputField.value.trim();
            if (!text || sendBtn.disabled) return;

            appendMessage(text, true);
            inputField.value = '';
            inputField.style.height = 'auto';
            sendBtn.disabled = true;
            showTyping();

            // 创建 AbortController 用于终止请求
            currentAbortController = new AbortController();
            setStreamingUI(true);

            let agentDiv = null;
            let fullText = '';

            try {
                const response = await fetch("/proxy_ask_stream", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: text, enabled_tools: getEnabledTools() }),
                    signal: currentAbortController.signal
                });

                const typingIndicator = document.getElementById('typing-indicator');
                if (typingIndicator) typingIndicator.remove();

                if (response.status === 401) {
                    appendMessage("⚠️ 登录已过期，请重新登录", false);
                    handleLogout();
                    return;
                }
                if (!response.ok) throw new Error("Agent 响应异常");

                // 创建空的 agent 消息气泡，后续逐步填充
                agentDiv = appendMessage('', false);

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\\n');
                    buffer = lines.pop(); // 保留不完整的行

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const payload = line.slice(6);
                        if (payload === '[DONE]') continue;

                        // 反转义：还原换行符
                        const text = payload.replace(/\\\\n/g, '\\n').replace(/\\\\\\\\/g, '\\\\');
                        fullText += text;

                        // 实时渲染 Markdown
                        agentDiv.innerHTML = marked.parse(fullText);
                        agentDiv.querySelectorAll('pre code').forEach((block) => {
                            if (!block.dataset.highlighted) {
                                hljs.highlightElement(block);
                                block.dataset.highlighted = 'true';
                            }
                        });
                        chatBox.scrollTop = chatBox.scrollHeight;
                    }
                }

                // 最终完整渲染一次（确保 Markdown 完整解析）
                if (fullText) {
                    agentDiv.innerHTML = marked.parse(fullText);
                    agentDiv.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
                    chatBox.scrollTop = chatBox.scrollHeight;
                }

                if (!fullText) {
                    agentDiv.innerHTML = '<span class="text-gray-400">（无响应）</span>';
                }
            } catch (error) {
                const typingIndicator = document.getElementById('typing-indicator');
                if (typingIndicator) typingIndicator.remove();
                if (error.name === 'AbortError') {
                    // 用户主动终止：保留已有内容，追加终止标记
                    if (agentDiv) {
                        fullText += '\\n\\n⚠️ 已终止思考';
                        agentDiv.innerHTML = marked.parse(fullText);
                    } else {
                        appendMessage("⚠️ 已终止思考", false);
                    }
                } else {
                    appendMessage("❌ 错误: " + error.message, false);
                }
            } finally {
                currentAbortController = null;
                setStreamingUI(false);
            }
        }

        inputField.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
        inputField.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
        });
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/proxy_login", methods=["POST"])
def proxy_login():
    """代理登录请求到后端 Agent"""
    user_id = request.json.get("user_id", "")
    password = request.json.get("password", "")

    try:
        r = requests.post(LOCAL_LOGIN_URL, json={"user_id": user_id, "password": password}, timeout=10)
        if r.status_code == 200:
            # 登录成功，在 Flask session 中记录
            session["user_id"] = user_id
            session["password"] = password  # 需要传给后端每次验证
            return jsonify(r.json())
        else:
            return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/proxy_ask", methods=["POST"])
def proxy_ask():
    # 从 Flask session 中获取已验证的用户信息
    user_id = session.get("user_id")
    password = session.get("password")
    if not user_id or not password:
        return jsonify({"error": "未登录"}), 401

    user_content = request.json.get("content")
    
    payload = {
        "user_id": user_id,
        "password": password,
        "text": user_content
    }
    
    try:
        r = requests.post(LOCAL_AGENT_URL, json=payload, timeout=120)
        if r.status_code == 401:
            session.clear()
            return jsonify(r.json()), 401
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/proxy_ask_stream", methods=["POST"])
def proxy_ask_stream():
    """流式代理：将 Agent 的 SSE 响应透传给前端"""
    user_id = session.get("user_id")
    password = session.get("password")
    if not user_id or not password:
        return jsonify({"error": "未登录"}), 401

    user_content = request.json.get("content")
    enabled_tools = request.json.get("enabled_tools")  # None or list
    payload = {
        "user_id": user_id,
        "password": password,
        "text": user_content,
        "enabled_tools": enabled_tools,
    }

    try:
        r = requests.post(LOCAL_AGENT_STREAM_URL, json=payload, stream=True, timeout=120)
        if r.status_code == 401:
            session.clear()
            return jsonify({"error": "认证失败"}), 401
        if r.status_code != 200:
            return jsonify({"error": f"Agent 返回 {r.status_code}"}), r.status_code

        def generate():
            for line in r.iter_lines(decode_unicode=True):
                if line:
                    yield line + "\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/proxy_cancel", methods=["POST"])
def proxy_cancel():
    """代理取消请求到后端 Agent"""
    user_id = session.get("user_id")
    password = session.get("password")
    if not user_id or not password:
        return jsonify({"error": "未登录"}), 401
    try:
        r = requests.post(LOCAL_AGENT_CANCEL_URL, json={"user_id": user_id, "password": password}, timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/proxy_tools")
def proxy_tools():
    """代理获取工具列表请求到后端 Agent"""
    try:
        r = requests.get(LOCAL_TOOLS_URL, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e), "tools": []}), 500

@app.route("/proxy_logout", methods=["POST"])
def proxy_logout():
    session.clear()
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT_FRONTEND", "51209")), debug=False)
