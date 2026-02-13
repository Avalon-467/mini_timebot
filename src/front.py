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

# OASIS Forum proxy
PORT_OASIS = int(os.getenv("PORT_OASIS", "51202"))
OASIS_BASE_URL = f"http://127.0.0.1:{PORT_OASIS}"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Xavier AnyControl | AI Agent</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">

    <!-- PWA / iOS Full-screen support -->
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="AnyControl">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="theme-color" content="#111827">
    <meta name="format-detection" content="telephone=no">
    <meta name="msapplication-tap-highlight" content="no">
    <meta name="msapplication-TileColor" content="#111827">
    <link rel="apple-touch-icon" href="https://img.icons8.com/fluency/180/robot-2.png">
    <link rel="apple-touch-icon" sizes="152x152" href="https://img.icons8.com/fluency/152/robot-2.png">
    <link rel="apple-touch-icon" sizes="180x180" href="https://img.icons8.com/fluency/180/robot-2.png">
    <link rel="apple-touch-icon" sizes="167x167" href="https://img.icons8.com/fluency/167/robot-2.png">
    <!-- iOS splash screens -->
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="manifest" href="/manifest.json">
    
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.2/marked.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>

    <style>
        /* === Native App Behavior (mobile only) === */
        html, body {
            overscroll-behavior: none;
        }
        @media (hover: none) and (pointer: coarse) {
            /* Mobile / touch devices only */
            html, body {
                -webkit-overflow-scrolling: touch;
                -webkit-user-select: none;
                user-select: none;
                -webkit-touch-callout: none;
                -webkit-tap-highlight-color: transparent;
                touch-action: manipulation;
                position: fixed;
                width: 100%;
                height: 100%;
                overflow: hidden;
            }
            /* Allow text selection only inside chat messages on mobile */
            .message-agent, .message-user, .markdown-body {
                -webkit-user-select: text;
                user-select: text;
            }
        }
        /* Safe area classes removed — no special notch/curved-screen handling */
        /* Splash screen */
        #app-splash {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: linear-gradient(135deg, #111827 0%, #1e3a5f 100%);
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            z-index: 99999; transition: opacity 0.5s ease;
        }
        #app-splash.fade-out { opacity: 0; pointer-events: none; }
        #app-splash .splash-icon { width: 80px; height: 80px; border-radius: 20px; margin-bottom: 16px; animation: splash-bounce 1s ease infinite; }
        #app-splash .splash-title { color: white; font-size: 22px; font-weight: 700; letter-spacing: 1px; }
        #app-splash .splash-sub { color: rgba(255,255,255,0.5); font-size: 12px; margin-top: 8px; }
        @keyframes splash-bounce { 0%,100% { transform: scale(1); } 50% { transform: scale(1.08); } }
        /* Offline banner */
        #offline-banner {
            display: none; position: fixed; top: 0; left: 0; right: 0;
            background: #ef4444; color: white; text-align: center;
            padding: 6px 0; font-size: 13px; font-weight: 600; z-index: 99998;
            padding-top: 6px;
        }
        #offline-banner.show { display: block; animation: slideDown 0.3s ease; }
        @keyframes slideDown { from { transform: translateY(-100%); } to { transform: translateY(0); } }

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

        /* OASIS Panel Styles */
        .oasis-panel { width: 380px; min-width: 320px; transition: width 0.3s ease; }
        .oasis-panel.collapsed-panel { width: 48px; min-width: 48px; }
        .oasis-panel.collapsed-panel .oasis-content { display: none; }
        .oasis-panel.collapsed-panel .oasis-expand-btn { display: flex; }
        .oasis-expand-btn { display: none; writing-mode: vertical-lr; text-orientation: mixed; }
        .oasis-topic-item { transition: all 0.2s ease; cursor: pointer; }
        .oasis-topic-item:hover { background: #eff6ff; }
        .oasis-topic-item.active { background: #dbeafe; border-left: 3px solid #2563eb; }
        .oasis-post { animation: slideIn 0.3s ease; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .oasis-vote-bar { height: 6px; border-radius: 3px; overflow: hidden; }
        .oasis-vote-up { background: #22c55e; }
        .oasis-vote-down { background: #ef4444; }
        .oasis-status-badge { font-size: 10px; padding: 2px 8px; border-radius: 9999px; font-weight: 600; }
        .oasis-status-pending { background: #fef3c7; color: #92400e; }
        .oasis-status-discussing { background: #dbeafe; color: #1e40af; animation: pulse-bg 2s infinite; }
        .oasis-status-concluded { background: #d1fae5; color: #065f46; }
        .oasis-status-error { background: #fee2e2; color: #991b1b; }
        @keyframes pulse-bg { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
        .oasis-expert-avatar { width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; color: white; flex-shrink: 0; }
        .expert-creative { background: linear-gradient(135deg, #f59e0b, #f97316); }
        .expert-critical { background: linear-gradient(135deg, #ef4444, #dc2626); }
        .expert-data { background: linear-gradient(135deg, #3b82f6, #2563eb); }
        .expert-synthesis { background: linear-gradient(135deg, #8b5cf6, #7c3aed); }
        .expert-default { background: linear-gradient(135deg, #6b7280, #4b5563); }
        .oasis-discussion-box { height: calc(100vh - 340px); overflow-y: auto; }
        .oasis-conclusion-box { background: linear-gradient(135deg, #f0fdf4, #ecfdf5); border: 1px solid #86efac; border-radius: 12px; padding: 12px; }
        .main-layout { display: flex; height: 100vh; max-width: 100%; }
        .chat-main { flex: 1; min-width: 0; max-width: 900px; display: flex; flex-direction: column; }

        /* === Mobile responsive === */
        @media (max-width: 768px) {
            .main-layout { flex-direction: column; }
            .chat-main { max-width: 100%; width: 100%; height: 100%; }
            .chat-container { height: auto !important; flex: 1; min-height: 0; overflow-y: auto; }
            /* OASIS: overlay mode on mobile */
            .oasis-divider { display: none !important; }
            .oasis-panel {
                position: fixed !important; top: 0; left: 0; right: 0; bottom: 0;
                width: 100% !important; min-width: 100% !important;
                z-index: 50; display: none;
            }
            .oasis-panel.mobile-open { display: flex !important; }
            .oasis-panel.collapsed-panel { display: none !important; }
            .oasis-panel .oasis-expand-btn { display: none !important; }
            /* Mobile: hide UID & session, hide desktop buttons, show hamburger */
            #uid-display, #session-display { display: none !important; }
            .desktop-only-btn { display: none !important; }
            .mobile-menu-btn { display: inline-flex !important; }
            /* Header: stack items on narrow screens */
            .mobile-header-top { flex-wrap: wrap; gap: 6px; }
            .mobile-header-actions { flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
            /* Reduce padding on mobile */
            #chat-box { padding: 12px !important; }
            .message-agent, .message-user { max-width: 92% !important; }
            /* Ensure input area stays visible */
            .p-2.sm\:p-4.border-t { 
                flex-shrink: 0 !important; 
                min-height: fit-content !important;
                position: relative !important;
                z-index: 5 !important;
            }
            /* Increase font size on mobile */
            .message-content, .message-agent, .message-user { font-size: 16px !important; }
            .message-content p, .message-content li { font-size: 16px !important; }
            #message-input, #message-input::placeholder { font-size: 16px !important; }
            .tool-tag { font-size: 14px !important; padding: 6px 12px !important; }
        }
        /* Hide mobile-only elements on desktop */
        @media (min-width: 769px) {
            .mobile-menu-wrapper { display: none !important; }
        }
        /* Mobile menu dropdown styles */
        .mobile-menu-btn { display: none; }
        .mobile-menu-dropdown {
            position: absolute; right: 0; top: 100%; margin-top: 6px;
            background: white; border: 1px solid #e5e7eb; border-radius: 10px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.12); z-index: 100;
            min-width: 140px; overflow: hidden;
        }
        .mobile-menu-item {
            display: block; width: 100%; text-align: left;
            padding: 10px 14px; font-size: 13px; color: #374151;
            border: none; background: none; cursor: pointer;
            transition: background 0.15s;
        }
        .mobile-menu-item:hover, .mobile-menu-item:active { background: #f3f4f6; }
        .mobile-menu-item + .mobile-menu-item { border-top: 1px solid #f3f4f6; }
        .oasis-divider { width: 1px; background: #e5e7eb; cursor: col-resize; flex-shrink: 0; }
        .oasis-divider:hover { background: #3b82f6; width: 3px; }
    </style>
</head>
<body class="bg-gray-100 font-sans leading-normal tracking-normal">

    <!-- Splash Screen -->
    <div id="app-splash">
        <img class="splash-icon" src="https://img.icons8.com/fluency/180/robot-2.png" alt="">
        <div class="splash-title">AnyControl</div>
        <div class="splash-sub">Xavier AI Agent</div>
    </div>

    <!-- Offline Banner -->
    <div id="offline-banner">⚠️ 网络已断开，请检查连接</div>

    <!-- ========== 登录页 ========== -->
    <div id="login-screen" class="min-h-screen flex items-center justify-center safe-top safe-bottom px-4" style="width:100%;height:100%;overflow:auto;">
        <div class="bg-white rounded-2xl shadow-2xl p-6 sm:p-8 w-full max-w-md border">
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

    <!-- ========== 主布局（聊天 + OASIS）（初始隐藏） ========== -->
    <div id="chat-screen" class="main-layout safe-top safe-bottom safe-left safe-right" style="display:none;">

        <!-- ===== 左侧：聊天区 ===== -->
        <div class="chat-main h-screen flex flex-col bg-white border-x border-gray-200 shadow-2xl">
            <header class="p-3 sm:p-4 border-b bg-white flex justify-between items-start sm:items-center sticky top-0 z-10 gap-2">
                <div class="flex items-center space-x-2 sm:space-x-3 mobile-header-top flex-shrink-0">
                    <div class="bg-blue-600 p-1.5 sm:p-2 rounded-lg text-white font-bold text-lg sm:text-xl">X</div>
                    <div>
                        <h1 class="text-sm sm:text-lg font-bold text-gray-800 leading-tight">AnyControl</h1>
                        <p class="text-[10px] sm:text-xs text-green-500 flex items-center">● 已加密</p>
                    </div>
                </div>
                <div class="flex items-center space-x-1 sm:space-x-2 mobile-header-actions flex-shrink-0">
                    <div id="uid-display" class="text-xs sm:text-sm font-mono bg-gray-100 px-2 sm:px-3 py-1 rounded border truncate max-w-[80px] sm:max-w-none"></div>
                    <div id="session-display" class="text-[10px] sm:text-xs font-mono bg-blue-50 text-blue-600 px-1.5 sm:px-2 py-1 rounded border border-blue-200 cursor-default" title="当前对话号"></div>
                    <!-- Desktop: show all buttons inline -->
                    <button onclick="handleNewSession()" class="desktop-only-btn text-[10px] sm:text-xs bg-green-50 text-green-600 hover:bg-green-100 px-1.5 sm:px-2 py-1 rounded border border-green-200 transition-colors" title="开启新对话">+新</button>
                    <button onclick="handleLogout()" class="desktop-only-btn text-[10px] sm:text-xs text-gray-400 hover:text-red-500 px-1.5 sm:px-2 py-1 rounded transition-colors" title="切换用户">退出</button>
                    <!-- Mobile: hamburger menu -->
                    <div class="mobile-menu-wrapper" style="position:relative;">
                        <button onclick="toggleMobileMenu()" class="mobile-menu-btn text-[10px] bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded border border-gray-300 transition-colors" title="更多操作">⋮</button>
                        <div id="mobile-menu-dropdown" class="mobile-menu-dropdown" style="display:none;">
                            <button onclick="handleNewSession(); closeMobileMenu();" class="mobile-menu-item">➕ 新对话</button>
                            <button onclick="toggleOasisMobile(); closeMobileMenu();" class="mobile-menu-item">🏛️ OASIS</button>
                            <button onclick="handleLogout(); closeMobileMenu();" class="mobile-menu-item text-red-500">🚪 退出</button>
                        </div>
                    </div>
                </div>
            </header>

            <div id="chat-box" class="chat-container overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6 flex-grow bg-gray-50">
                <div class="flex justify-start">
                    <div class="message-agent bg-white border p-4 max-w-[85%] shadow-sm text-gray-700">
                        你好！我是 Xavier 智能助手。我已经准备好为你服务，请输入你的指令。
                    </div>
                </div>
            </div>

            <div class="p-2 sm:p-4 border-t bg-white flex-shrink-0">
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
                <div class="flex items-end space-x-2 sm:space-x-3">
                    <div class="flex-grow">
                        <textarea id="user-input" rows="1" 
                            class="w-full p-2 sm:p-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none transition-all text-sm sm:text-base"
                            placeholder="输入指令..."></textarea>
                    </div>
                    <button onclick="handleSend()" id="send-btn"
                        class="bg-blue-600 hover:bg-blue-700 text-white px-4 sm:px-6 py-2 sm:py-3 rounded-xl transition-all font-bold shadow-lg h-[42px] sm:h-[50px] text-sm sm:text-base flex-shrink-0">
                        发送
                    </button>
                    <button onclick="handleCancel()" id="cancel-btn"
                        class="bg-red-500 hover:bg-red-600 text-white px-4 sm:px-6 py-2 sm:py-3 rounded-xl transition-all font-bold shadow-lg h-[42px] sm:h-[50px] text-sm sm:text-base flex-shrink-0"
                        style="display:none;">
                        终止
                    </button>
                </div>
                <p class="text-[10px] text-center text-gray-400 mt-2 sm:mt-3 font-mono hidden sm:block">Secured by Nginx Reverse Proxy & SSH Tunnel</p>
            </div>
        </div>

        <!-- ===== 分割线 ===== -->
        <div class="oasis-divider" id="oasis-divider"></div>

        <!-- ===== 右侧：OASIS 讨论面板 ===== -->
        <div class="oasis-panel collapsed-panel bg-white border-l border-gray-200 flex flex-col h-screen" id="oasis-panel">
            <!-- Collapsed state expand button -->
            <div class="oasis-expand-btn items-center justify-center h-full text-gray-400 hover:text-blue-600 cursor-pointer text-sm font-bold" onclick="toggleOasisPanel()">
                🏛️ O A S I S
            </div>

            <!-- Panel content -->
            <div class="oasis-content flex flex-col h-full">
                <!-- Header -->
                <div class="p-3 border-b bg-gradient-to-r from-purple-50 to-blue-50 flex items-center justify-between flex-shrink-0">
                    <div class="flex items-center space-x-2">
                        <span class="text-lg">🏛️</span>
                        <div>
                            <h2 class="text-sm font-bold text-gray-800">OASIS 讨论论坛</h2>
                            <p class="text-[10px] text-gray-500">多专家并行讨论系统</p>
                        </div>
                    </div>
                    <div class="flex items-center space-x-1">
                        <button onclick="refreshOasisTopics()" class="text-gray-400 hover:text-blue-600 p-1 rounded transition-colors" title="刷新">🔄</button>
                        <button onclick="toggleOasisPanel()" class="text-gray-400 hover:text-red-500 p-1 rounded transition-colors" title="收起">✕</button>
                    </div>
                </div>

                <!-- Topic list view -->
                <div id="oasis-topic-list-view" class="flex flex-col flex-1 overflow-hidden">
                    <div class="p-3 border-b flex-shrink-0">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-semibold text-gray-600">📋 讨论话题</span>
                            <span id="oasis-topic-count" class="text-[10px] text-gray-400"></span>
                        </div>
                    </div>
                    <div id="oasis-topic-list" class="flex-1 overflow-y-auto">
                        <div class="p-6 text-center text-gray-400 text-sm">
                            <div class="text-3xl mb-2">🏛️</div>
                            <p>暂无讨论话题</p>
                            <p class="text-xs mt-1">在聊天中让 Agent 发起 OASIS 讨论</p>
                        </div>
                    </div>
                </div>

                <!-- Topic detail view (hidden by default) -->
                <div id="oasis-detail-view" class="flex flex-col flex-1 overflow-hidden" style="display:none;">
                    <!-- Detail header -->
                    <div class="p-3 border-b flex-shrink-0">
                        <div class="flex items-center space-x-2">
                            <button onclick="showOasisTopicList()" class="text-gray-400 hover:text-blue-600 text-sm">← 返回</button>
                            <span id="oasis-detail-status" class="oasis-status-badge"></span>
                            <span id="oasis-detail-round" class="text-[10px] text-gray-400"></span>
                        </div>
                        <p id="oasis-detail-question" class="text-sm font-semibold text-gray-800 mt-1 line-clamp-2"></p>
                    </div>

                    <!-- Posts stream -->
                    <div id="oasis-posts-box" class="oasis-discussion-box flex-1 p-3 space-y-3 bg-gray-50">
                        <!-- Posts will be injected here -->
                    </div>

                    <!-- Conclusion area -->
                    <div id="oasis-conclusion-area" class="p-3 border-t flex-shrink-0" style="display:none;">
                        <div class="oasis-conclusion-box">
                            <div class="flex items-center space-x-1 mb-2">
                                <span class="text-sm">🏆</span>
                                <span class="text-xs font-bold text-green-800">讨论结论</span>
                            </div>
                            <p id="oasis-conclusion-text" class="text-xs text-gray-700 leading-relaxed"></p>
                        </div>
                    </div>
                </div>
            </div>
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
        let currentSessionId = null;
        let currentAbortController = null;

        // ===== Session (conversation) ID management =====
        function generateSessionId() {
            return Date.now().toString(36) + Math.random().toString(36).substr(2, 4);
        }

        function initSession() {
            let saved = sessionStorage.getItem('sessionId');
            if (!saved) {
                saved = generateSessionId();
                sessionStorage.setItem('sessionId', saved);
            }
            currentSessionId = saved;
            updateSessionDisplay();
        }

        function updateSessionDisplay() {
            const el = document.getElementById('session-display');
            if (el && currentSessionId) {
                el.textContent = '#' + currentSessionId.slice(-6);
                el.title = '对话号: ' + currentSessionId;
            }
        }

        function handleNewSession() {
            if (!confirm('开启新对话？当前对话的历史记录将保留，可通过切回对话号恢复。')) return;
            currentSessionId = generateSessionId();
            sessionStorage.setItem('sessionId', currentSessionId);
            updateSessionDisplay();
            // Clear chat box for new conversation
            const chatBox = document.getElementById('chat-box');
            chatBox.innerHTML = `
                <div class="flex justify-start">
                    <div class="message-agent bg-white border p-4 max-w-[85%] shadow-sm text-gray-700">
                        🆕 已开启新对话。我是 Xavier 智能助手，请输入你的指令。
                    </div>
                </div>`;
        }

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
                sessionStorage.setItem('userId', name);
                sessionStorage.setItem('authToken', data.token || '');
                initSession();

                document.getElementById('uid-display').textContent = 'UID: ' + name;
                document.getElementById('login-screen').style.display = 'none';
                document.getElementById('chat-screen').style.display = 'flex';
                document.getElementById('user-input').focus();
                loadTools();
                refreshOasisTopics(); // Load OASIS topics after login
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
            currentSessionId = null;
            sessionStorage.removeItem('userId');
            sessionStorage.removeItem('authToken');
            sessionStorage.removeItem('sessionId');
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
            // Stop OASIS polling
            stopOasisPolling();
        }

        // ===== Tool Panel 逻辑 =====
        let toolPanelOpen = false;
        let allTools = [];
        let enabledToolSet = new Set();

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
                enabledToolSet = new Set(tools.map(t => t.name));
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

        // Session check
        (function checkSession() {
            const saved = sessionStorage.getItem('userId');
            if (saved) {
                currentUserId = saved;
                initSession();
                document.getElementById('uid-display').textContent = 'UID: ' + saved;
                document.getElementById('login-screen').style.display = 'none';
                document.getElementById('chat-screen').style.display = 'flex';
                loadTools();
                refreshOasisTopics();
            }
        })();

        // Login input handlers
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
            if (currentAbortController) {
                currentAbortController.abort();
                currentAbortController = null;
            }
            try {
                await fetch("/proxy_cancel", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ session_id: currentSessionId })
                });
            } catch(e) { /* ignore */ }
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

            currentAbortController = new AbortController();
            setStreamingUI(true);

            let agentDiv = null;
            let fullText = '';

            try {
                const response = await fetch("/proxy_ask_stream", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: text, enabled_tools: getEnabledTools(), session_id: currentSessionId }),
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

                agentDiv = appendMessage('', false);

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const payload = line.slice(6);
                        if (payload === '[DONE]') continue;

                        const text = payload.replace(/\\\\n/g, '\\n').replace(/\\\\\\\\/g, '\\\\');
                        fullText += text;

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

                if (fullText) {
                    agentDiv.innerHTML = marked.parse(fullText);
                    agentDiv.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
                    chatBox.scrollTop = chatBox.scrollHeight;
                }

                if (!fullText) {
                    agentDiv.innerHTML = '<span class="text-gray-400">（无响应）</span>';
                }

                // After agent response, refresh OASIS topics (in case a new discussion was started)
                setTimeout(() => refreshOasisTopics(), 1000);

            } catch (error) {
                const typingIndicator = document.getElementById('typing-indicator');
                if (typingIndicator) typingIndicator.remove();
                if (error.name === 'AbortError') {
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

        // ================================================================
        // ===== OASIS 讨论面板逻辑 =====
        // ================================================================

        let oasisPanelOpen = false;
        let oasisCurrentTopicId = null;
        let oasisPollingTimer = null;
        let oasisStreamReader = null;

        // Expert avatar mapping
        const expertAvatars = {
            '创意专家': { cls: 'expert-creative', icon: '💡' },
            '批判专家': { cls: 'expert-critical', icon: '🔍' },
            '数据分析师': { cls: 'expert-data', icon: '📊' },
            '综合顾问': { cls: 'expert-synthesis', icon: '🎯' },
        };

        function getExpertAvatar(name) {
            return expertAvatars[name] || { cls: 'expert-default', icon: '🤖' };
        }

        function getStatusBadge(status) {
            const map = {
                'pending': { cls: 'oasis-status-pending', text: '等待中' },
                'discussing': { cls: 'oasis-status-discussing', text: '讨论中' },
                'concluded': { cls: 'oasis-status-concluded', text: '已完成' },
                'error': { cls: 'oasis-status-error', text: '出错' },
            };
            return map[status] || { cls: 'oasis-status-pending', text: status };
        }

        function formatTime(ts) {
            const d = new Date(ts * 1000);
            return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        }

        function toggleOasisPanel() {
            const panel = document.getElementById('oasis-panel');
            oasisPanelOpen = !oasisPanelOpen;
            if (oasisPanelOpen) {
                panel.classList.remove('collapsed-panel');
                panel.classList.remove('mobile-open');
                refreshOasisTopics();
            } else {
                panel.classList.add('collapsed-panel');
                panel.classList.remove('mobile-open');
                stopOasisPolling();
            }
        }

        function toggleOasisMobile() {
            const panel = document.getElementById('oasis-panel');
            if (panel.classList.contains('mobile-open')) {
                panel.classList.remove('mobile-open');
                stopOasisPolling();
            } else {
                panel.classList.remove('collapsed-panel');
                panel.classList.add('mobile-open');
                refreshOasisTopics();
            }
        }

        function toggleMobileMenu() {
            const dd = document.getElementById('mobile-menu-dropdown');
            if (dd.style.display === 'none') {
                dd.style.display = 'block';
                // close when tapping outside
                setTimeout(() => document.addEventListener('click', closeMobileMenuOutside, { once: true }), 0);
            } else {
                dd.style.display = 'none';
            }
        }
        function closeMobileMenu() {
            document.getElementById('mobile-menu-dropdown').style.display = 'none';
        }
        function closeMobileMenuOutside(e) {
            const wrapper = document.querySelector('.mobile-menu-wrapper');
            if (!wrapper.contains(e.target)) closeMobileMenu();
        }

        function stopOasisPolling() {
            if (oasisPollingTimer) {
                clearInterval(oasisPollingTimer);
                oasisPollingTimer = null;
            }
            if (oasisStreamReader) {
                oasisStreamReader.cancel();
                oasisStreamReader = null;
            }
        }

        async function refreshOasisTopics() {
            try {
                const resp = await fetch('/proxy_oasis/topics');
                console.log('[OASIS] Topics response status:', resp.status);
                if (!resp.ok) {
                    console.error('[OASIS] Failed to fetch topics:', resp.status);
                    return;
                }
                const topics = await resp.json();
                console.log('[OASIS] Topics data:', topics);
                renderTopicList(topics);
            } catch (e) {
                console.error('[OASIS] Failed to load topics:', e);
            }
        }

        function renderTopicList(topics) {
            const container = document.getElementById('oasis-topic-list');
            const countEl = document.getElementById('oasis-topic-count');
            countEl.textContent = topics.length + ' 个话题';

            if (topics.length === 0) {
                container.innerHTML = `
                    <div class="p-6 text-center text-gray-400 text-sm">
                        <div class="text-3xl mb-2">🏛️</div>
                        <p>暂无讨论话题</p>
                        <p class="text-xs mt-1">在聊天中让 Agent 发起 OASIS 讨论</p>
                    </div>`;
                return;
            }

            // Sort: discussing first, then by created_at desc
            topics.sort((a, b) => {
                if (a.status === 'discussing' && b.status !== 'discussing') return -1;
                if (b.status === 'discussing' && a.status !== 'discussing') return 1;
                return (b.created_at || 0) - (a.created_at || 0);
            });

            container.innerHTML = topics.map(t => {
                const badge = getStatusBadge(t.status);
                const isActive = t.topic_id === oasisCurrentTopicId;
                return `
                    <div class="oasis-topic-item p-3 border-b ${isActive ? 'active' : ''}" onclick="openOasisTopic('${t.topic_id}')">
                        <div class="flex items-center justify-between mb-1">
                            <span class="oasis-status-badge ${badge.cls}">${badge.text}</span>
                            <span class="text-[10px] text-gray-400">${t.created_at ? formatTime(t.created_at) : ''}</span>
                        </div>
                        <p class="text-sm text-gray-800 font-medium line-clamp-2">${escapeHtml(t.question)}</p>
                        <div class="flex items-center space-x-3 mt-1 text-[10px] text-gray-400">
                            <span>💬 ${t.post_count || 0} 帖</span>
                            <span>🔄 ${t.current_round}/${t.max_rounds} 轮</span>
                        </div>
                    </div>`;
            }).join('');
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function openOasisTopic(topicId) {
            oasisCurrentTopicId = topicId;
            stopOasisPolling();

            // Switch to detail view
            document.getElementById('oasis-topic-list-view').style.display = 'none';
            document.getElementById('oasis-detail-view').style.display = 'flex';

            // Load topic detail
            await loadTopicDetail(topicId);
        }

        function showOasisTopicList() {
            stopOasisPolling();
            oasisCurrentTopicId = null;
            document.getElementById('oasis-detail-view').style.display = 'none';
            document.getElementById('oasis-topic-list-view').style.display = 'flex';
            refreshOasisTopics();
        }

        async function loadTopicDetail(topicId) {
            try {
                const resp = await fetch(`/proxy_oasis/topics/${topicId}`);
                console.log('[OASIS] Detail response status:', resp.status);
                if (!resp.ok) {
                    console.error('[OASIS] Failed to fetch detail:', resp.status);
                    return;
                }
                const detail = await resp.json();
                console.log('[OASIS] Detail data:', detail);
                console.log('[OASIS] Posts count:', (detail.posts || []).length);
                renderTopicDetail(detail);

                // If still discussing, start polling for updates
                if (detail.status === 'discussing' || detail.status === 'pending') {
                    startDetailPolling(topicId);
                }
            } catch (e) {
                console.warn('Failed to load topic detail:', e);
            }
        }

        function renderTopicDetail(detail) {
            const badge = getStatusBadge(detail.status);
            document.getElementById('oasis-detail-status').className = 'oasis-status-badge ' + badge.cls;
            document.getElementById('oasis-detail-status').textContent = badge.text;
            document.getElementById('oasis-detail-round').textContent = `第 ${detail.current_round}/${detail.max_rounds} 轮`;
            document.getElementById('oasis-detail-question').textContent = detail.question;

            renderPosts(detail.posts || []);

            // Show/hide conclusion
            const conclusionArea = document.getElementById('oasis-conclusion-area');
            if (detail.conclusion && detail.status === 'concluded') {
                document.getElementById('oasis-conclusion-text').textContent = detail.conclusion;
                conclusionArea.style.display = 'block';
            } else {
                conclusionArea.style.display = 'none';
            }
        }

        function renderPosts(posts) {
            const box = document.getElementById('oasis-posts-box');

            if (posts.length === 0) {
                box.innerHTML = `
                    <div class="text-center text-gray-400 text-sm py-8">
                        <div class="text-2xl mb-2">💭</div>
                        <p>等待专家发言...</p>
                    </div>`;
                return;
            }

            box.innerHTML = posts.map(p => {
                const avatar = getExpertAvatar(p.author);
                const isReply = p.reply_to !== null && p.reply_to !== undefined;
                const totalVotes = p.upvotes + p.downvotes;
                const upPct = totalVotes > 0 ? (p.upvotes / totalVotes * 100) : 50;

                return `
                    <div class="oasis-post bg-white rounded-xl p-3 border shadow-sm ${isReply ? 'ml-4 border-l-2 border-l-blue-300' : ''}">
                        <div class="flex items-start space-x-2">
                            <div class="oasis-expert-avatar ${avatar.cls}" title="${escapeHtml(p.author)}">${avatar.icon}</div>
                            <div class="flex-1 min-w-0">
                                <div class="flex items-center justify-between">
                                    <span class="text-xs font-semibold text-gray-700">${escapeHtml(p.author)}</span>
                                    <div class="flex items-center space-x-2 text-[10px] text-gray-400">
                                        ${isReply ? '<span>↩️ #' + p.reply_to + '</span>' : ''}
                                        <span>#${p.id}</span>
                                    </div>
                                </div>
                                <p class="text-xs text-gray-600 mt-1 leading-relaxed">${escapeHtml(p.content)}</p>
                                <div class="flex items-center space-x-3 mt-2">
                                    <div class="flex items-center space-x-1">
                                        <span class="text-[10px]">👍 ${p.upvotes}</span>
                                        <span class="text-[10px]">👎 ${p.downvotes}</span>
                                    </div>
                                    ${totalVotes > 0 ? `
                                        <div class="flex-1 oasis-vote-bar flex">
                                            <div class="oasis-vote-up" style="width: ${upPct}%"></div>
                                            <div class="oasis-vote-down" style="width: ${100 - upPct}%"></div>
                                        </div>` : ''}
                                </div>
                            </div>
                        </div>
                    </div>`;
            }).join('');

            // Auto-scroll to bottom
            box.scrollTop = box.scrollHeight;
        }

        function startDetailPolling(topicId) {
            stopOasisPolling();
            let lastPostCount = 0;
            let errorCount = 0;
            oasisPollingTimer = setInterval(async () => {
                if (oasisCurrentTopicId !== topicId) {
                    stopOasisPolling();
                    return;
                }
                try {
                    const resp = await fetch(`/proxy_oasis/topics/${topicId}`);
                    if (!resp.ok) {
                        errorCount++;
                        console.warn(`OASIS polling error: HTTP ${resp.status}`);
                        if (errorCount >= 5) {
                            console.error('OASIS polling failed 5 times, stopping');
                            stopOasisPolling();
                        }
                        return;
                    }
                    errorCount = 0;
                    const detail = await resp.json();
                    
                    // Only re-render if posts changed
                    const currentPostCount = (detail.posts || []).length;
                    if (currentPostCount !== lastPostCount || detail.status !== 'discussing') {
                        renderTopicDetail(detail);
                        lastPostCount = currentPostCount;
                    }

                    // Stop polling when discussion ends
                    if (detail.status === 'concluded' || detail.status === 'error') {
                        stopOasisPolling();
                        refreshOasisTopics();
                    }
                } catch (e) {
                    errorCount++;
                    console.warn('OASIS polling error:', e);
                }
            }, 1500); // Poll every 1.5 seconds for faster updates
        }

        // Auto-refresh topic list periodically when panel is open
        setInterval(() => {
            if (oasisPanelOpen && !oasisCurrentTopicId && currentUserId) {
                refreshOasisTopics();
            }
        }, 10000); // Every 10 seconds
    </script>

    <script>
    // === Native App Enhancements ===

    // 1. Splash screen dismiss
    window.addEventListener('load', () => {
        setTimeout(() => {
            const splash = document.getElementById('app-splash');
            if (splash) {
                splash.classList.add('fade-out');
                setTimeout(() => splash.remove(), 600);
            }
        }, 800);
    });

    // 2. Prevent pull-to-refresh and overscroll bounce
    document.addEventListener('touchmove', function(e) {
        // Allow scrolling inside scrollable containers
        let el = e.target;
        while (el && el !== document.body) {
            const style = window.getComputedStyle(el);
            if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight > el.clientHeight) {
                return; // Allow scroll inside this element
            }
            el = el.parentElement;
        }
        e.preventDefault();
    }, { passive: false });

    // 3. Prevent double-tap zoom
    let lastTouchEnd = 0;
    document.addEventListener('touchend', function(e) {
        const now = Date.now();
        if (now - lastTouchEnd <= 300) {
            e.preventDefault();
        }
        lastTouchEnd = now;
    }, false);

    // 4. Prevent pinch zoom
    document.addEventListener('gesturestart', function(e) {
        e.preventDefault();
    });
    document.addEventListener('gesturechange', function(e) {
        e.preventDefault();
    });

    // 5. Prevent context menu on long press - mobile only (except in chat messages)
    const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    if (isTouchDevice) {
        document.addEventListener('contextmenu', function(e) {
            const allowed = e.target.closest('.message-agent, .message-user, .markdown-body, textarea, input');
            if (!allowed) {
                e.preventDefault();
            }
        });
    }

    // 6. Online/Offline detection
    function updateOnlineStatus() {
        const banner = document.getElementById('offline-banner');
        if (navigator.onLine) {
            banner.classList.remove('show');
        } else {
            banner.classList.add('show');
        }
    }
    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);

    // 7. Register Service Worker for PWA caching
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }

    // 8. iOS standalone: handle navigation to stay in-app
    if (window.navigator.standalone) {
        document.addEventListener('click', function(e) {
            const a = e.target.closest('a');
            if (a && a.href && !a.target && a.hostname === location.hostname) {
                e.preventDefault();
                location.href = a.href;
            }
        });
    }

    // 9. Keyboard handling for mobile/PWA using visualViewport
    if (isTouchDevice && window.visualViewport) {
        const chatMain = document.querySelector('.chat-main');
        const inputWrapper = document.querySelector('.p-2.sm\\:p-4.border-t');
        
        let pendingUpdate = null;
        function updateLayout() {
            const viewportHeight = window.visualViewport.height;
            const keyboardHeight = window.innerHeight - viewportHeight;
            
            if (keyboardHeight > 50) {
                // Keyboard is open
                document.body.style.height = viewportHeight + 'px';
                if (chatMain) chatMain.style.height = viewportHeight + 'px';
                // Scroll input into view
                if (inputWrapper) {
                    inputWrapper.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            } else {
                // Keyboard is closed
                document.body.style.height = '100vh';
                if (chatMain) chatMain.style.height = '100%';
            }
        }
        
        window.visualViewport.addEventListener('resize', () => {
            if (pendingUpdate) cancelAnimationFrame(pendingUpdate);
            pendingUpdate = requestAnimationFrame(updateLayout);
        });
        window.visualViewport.addEventListener('scroll', updateLayout);
        
        // Initial setup
        updateLayout();
    }
    
    // Fallback for older iOS
    if (isTouchDevice) {
        const inputEl = document.getElementById('user-input');
        if (inputEl) {
            inputEl.addEventListener('focus', () => {
                setTimeout(() => {
                    // For PWA standalone mode
                    if (window.visualViewport) {
                        document.body.style.height = window.visualViewport.height + 'px';
                    }
                }, 100);
            });
            inputEl.addEventListener('blur', () => {
                setTimeout(() => {
                    if (window.visualViewport) {
                        document.body.style.height = '100vh';
                    }
                }, 100);
            });
        }
    }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/manifest.json")
def manifest():
    """Serve PWA manifest for iOS/Android Add-to-Home-Screen support."""
    manifest_data = {
        "name": "Xavier AnyControl",
        "short_name": "AnyControl",
        "description": "Xavier AI Agent - Intelligent Control Assistant",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#111827",
        "theme_color": "#111827",
        "lang": "zh-CN",
        "categories": ["productivity", "utilities"],
        "icons": [
            {
                "src": "https://img.icons8.com/fluency/192/robot-2.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "https://img.icons8.com/fluency/512/robot-2.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    return app.response_class(
        response=__import__("json").dumps(manifest_data),
        mimetype="application/manifest+json"
    )


@app.route("/sw.js")
def service_worker():
    """Serve Service Worker for PWA offline support and caching."""
    sw_code = """
// Xavier AnyControl Service Worker
const CACHE_NAME = 'anycontrol-v1';
const PRECACHE_URLS = ['/'];

self.addEventListener('install', event => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    // Network-first strategy for API calls, cache-first for static assets
    if (event.request.url.includes('/proxy_') || event.request.url.includes('/ask')) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
    } else {
        event.respondWith(
            caches.match(event.request).then(cached => {
                const fetched = fetch(event.request).then(response => {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    return response;
                }).catch(() => cached);
                return cached || fetched;
            })
        );
    }
});
"""
    return app.response_class(
        response=sw_code,
        mimetype="application/javascript",
        headers={"Service-Worker-Allowed": "/"}
    )


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
    session_id = request.json.get("session_id", "default")
    payload = {
        "user_id": user_id,
        "password": password,
        "text": user_content,
        "enabled_tools": enabled_tools,
        "session_id": session_id,
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
    session_id = request.json.get("session_id", "default") if request.is_json else "default"
    try:
        r = requests.post(LOCAL_AGENT_CANCEL_URL, json={"user_id": user_id, "password": password, "session_id": session_id}, timeout=5)
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


# ===== OASIS Proxy Routes =====

@app.route("/proxy_oasis/topics")
def proxy_oasis_topics():
    """Proxy: list all OASIS discussion topics."""
    # Note: OASIS is a public forum, don't filter by user_id
    try:
        print(f"[OASIS Proxy] Fetching topics from {OASIS_BASE_URL}/topics")
        r = requests.get(f"{OASIS_BASE_URL}/topics", timeout=10)
        print(f"[OASIS Proxy] Response status: {r.status_code}, count: {len(r.json()) if r.text else 0}")
        return jsonify(r.json()), r.status_code
    except Exception as e:
        print(f"[OASIS Proxy] Error fetching topics: {e}")
        return jsonify([]), 200  # Return empty list on error


@app.route("/proxy_oasis/topics/<topic_id>")
def proxy_oasis_topic_detail(topic_id):
    """Proxy: get full detail of a specific OASIS discussion."""
    try:
        url = f"{OASIS_BASE_URL}/topics/{topic_id}"
        print(f"[OASIS Proxy] Fetching topic detail from {url}")
        r = requests.get(url, timeout=10)
        print(f"[OASIS Proxy] Detail response status: {r.status_code}")
        return jsonify(r.json()), r.status_code
    except Exception as e:
        print(f"[OASIS Proxy] Error fetching topic detail: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/proxy_oasis/topics/<topic_id>/stream")
def proxy_oasis_topic_stream(topic_id):
    """Proxy: SSE stream for real-time OASIS discussion updates."""
    try:
        r = requests.get(f"{OASIS_BASE_URL}/topics/{topic_id}/stream", stream=True, timeout=300)
        if r.status_code != 200:
            return jsonify({"error": f"OASIS returned {r.status_code}"}), r.status_code

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


@app.route("/proxy_oasis/experts")
def proxy_oasis_experts():
    """Proxy: list all OASIS expert agents."""
    try:
        r = requests.get(f"{OASIS_BASE_URL}/experts", timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT_FRONTEND", "51209")), debug=False)
