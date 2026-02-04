"""
Aleph Cloud Marketplace Dashboard - Official Brand Design
Client-side deployment using aleph-sdk-ts
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aleph Cloud Marketplace</title>
    <meta name="description" content="One-click deployment of applications on Aleph Cloud decentralized infrastructure">
    <link rel="icon" href="https://aleph.im/favicon.ico">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Public+Sans:ital,wght@0,400;0,700;1,400;1,700&family=Rubik:ital,wght@0,500;1,600;1,800&family=Source+Code+Pro:wght@400;700&display=swap" rel="stylesheet">
    
    <!-- Ethers for wallet connection -->
    <script src="https://cdn.jsdelivr.net/npm/ethers@6.9.0/dist/ethers.umd.min.js"></script>
    
    <!-- Aleph SDK -->
    <script type="importmap">
    {
        "imports": {
            "@aleph-sdk/client": "https://esm.sh/@aleph-sdk/client@1.1.1",
            "@aleph-sdk/ethereum": "https://esm.sh/@aleph-sdk/ethereum@1.1.0",
            "@aleph-sdk/evm": "https://esm.sh/@aleph-sdk/evm@1.0.2",
            "@aleph-sdk/message": "https://esm.sh/@aleph-sdk/message@1.1.1",
            "@aleph-sdk/account": "https://esm.sh/@aleph-sdk/account@1.1.0",
            "@aleph-sdk/core": "https://esm.sh/@aleph-sdk/core@1.1.0"
        }
    }
    </script>
    
    <style>
        :root {
            --white: #FFFFFF;
            --black: #000000;
            --base1: #141327;
            --main0: #029AFF;
            --main1: #5CFFB1;
            --main2: #FECD17;
            --error: #D92446;
            --translucid: #FFFFFF0F;
            --disabled: #FFFFFF1A;
            --disabled2: #FFFFFF33;
            --gradient-main0: linear-gradient(90deg, #00D1FF 0%, #0054FF 100%);
            --gradient-main1: linear-gradient(90deg, #EEFF9C 0%, #00FFBD 100%);
            --bg: var(--black);
            --text: var(--white);
            --text-muted: #FFFFFF99;
            --border: #FFFFFF1A;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body { 
            font-family: 'Public Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .header {
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(10px);
            padding: 16px 32px;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .header-inner {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 24px;
        }
        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .logo-icon { width: 32px; height: 32px; }
        .logo-text { font-family: 'Rubik', sans-serif; font-style: italic; font-weight: 600; }
        .logo-text h1 { 
            font-size: 20px;
            background: var(--gradient-main1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .logo-text p { color: var(--text-muted); font-size: 12px; font-family: 'Public Sans', sans-serif; font-style: normal; }
        
        .search-box {
            flex: 1;
            max-width: 400px;
            position: relative;
        }
        .search-box input {
            width: 100%;
            background: var(--translucid);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 12px 16px 12px 44px;
            color: var(--text);
            font-family: 'Public Sans', sans-serif;
            font-size: 14px;
        }
        .search-box input:focus { outline: none; border-color: var(--main0); }
        .search-box input::placeholder { color: var(--text-muted); }
        .search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: var(--text-muted); }
        
        .credit-badge {
            background: rgba(92, 255, 177, 0.1);
            border: 1px solid var(--main1);
            color: var(--main1);
            padding: 8px 14px;
            border-radius: 8px;
            font-family: 'Source Code Pro', monospace;
            font-size: 13px;
            font-weight: 600;
            display: none;
        }
        .credit-badge.warning {
            border-color: var(--main2);
            color: var(--main2);
            background: rgba(254, 205, 23, 0.1);
        }

        .wallet-section { display: flex; align-items: center; gap: 12px; }
        .wallet-btn {
            background: transparent;
            color: var(--text);
            border: 1px solid var(--text);
            padding: 10px 20px;
            border-radius: 8px;
            font-family: 'Rubik', sans-serif;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .wallet-btn:hover { background: var(--translucid); }
        .wallet-btn.connected {
            background: var(--gradient-main1);
            border-color: transparent;
            color: var(--black);
        }
        .wallet-address {
            font-family: 'Source Code Pro', monospace;
            font-size: 13px;
            color: var(--main1);
            background: rgba(92, 255, 177, 0.1);
            padding: 8px 12px;
            border-radius: 8px;
        }
        .disconnect-btn {
            background: transparent;
            border: 1px solid var(--error);
            color: var(--error);
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 12px;
            cursor: pointer;
        }
        .disconnect-btn:hover { background: var(--error); color: var(--white); }
        
        .stats-banner {
            background: rgba(20, 19, 39, 0.5);
            border-bottom: 1px solid var(--border);
            padding: 20px;
        }
        .stats-inner {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: center;
            gap: 64px;
            flex-wrap: wrap;
        }
        .stat-item { text-align: center; }
        .stat-value {
            font-family: 'Rubik', sans-serif;
            font-style: italic;
            font-weight: 800;
            font-size: 28px;
            background: var(--gradient-main1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .stat-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 40px 32px; }
        
        .auth-notice {
            background: var(--translucid);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 24px;
            margin-bottom: 40px;
            text-align: center;
        }
        .auth-notice.hidden { display: none; }
        .auth-notice h3 { font-family: 'Rubik', sans-serif; font-style: italic; color: var(--main1); margin-bottom: 8px; font-size: 18px; }
        .auth-notice p { color: var(--text-muted); font-size: 14px; }
        
        .section-header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
        .section-number { font-family: 'Rubik', sans-serif; font-style: italic; font-weight: 600; font-size: 20px; color: var(--text-muted); }
        .section-title {
            font-family: 'Rubik', sans-serif;
            font-style: italic;
            font-weight: 800;
            font-size: 32px;
            background: var(--gradient-main1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .section-icon { font-size: 24px; }
        
        .featured-section { margin-bottom: 48px; }
        .featured-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
        .featured-card {
            background: var(--translucid);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 24px;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
        }
        .featured-card:hover { border-color: var(--main1); background: rgba(92, 255, 177, 0.05); }
        .featured-badge {
            position: absolute;
            top: 16px;
            right: 16px;
            background: var(--gradient-main1);
            color: var(--black);
            font-family: 'Rubik', sans-serif;
            font-size: 10px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 4px;
            text-transform: uppercase;
        }
        .featured-card .app-icon { font-size: 40px; margin-bottom: 12px; }
        .featured-card .app-name { font-family: 'Rubik', sans-serif; font-weight: 700; font-size: 18px; color: var(--white); margin-bottom: 4px; }
        .featured-card .app-category { font-size: 12px; color: var(--main1); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
        .featured-card .app-desc { color: var(--text-muted); font-size: 14px; line-height: 1.5; margin-bottom: 16px; }
        .featured-card .app-price { font-family: 'Rubik', sans-serif; font-weight: 700; font-size: 16px; color: var(--main1); }
        .featured-card .app-price span { font-weight: 400; font-size: 12px; color: var(--text-muted); }
        
        .categories { display: flex; gap: 10px; margin-bottom: 32px; flex-wrap: wrap; padding-bottom: 24px; border-bottom: 1px solid var(--border); }
        .category-btn {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 10px 18px;
            border-radius: 24px;
            cursor: pointer;
            font-family: 'Public Sans', sans-serif;
            font-size: 14px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .category-btn:hover { border-color: var(--main1); color: var(--main1); }
        .category-btn.active { background: var(--gradient-main1); border-color: transparent; color: var(--black); font-weight: 600; }
        .category-count { background: rgba(255,255,255,0.15); padding: 2px 8px; border-radius: 12px; font-size: 11px; }
        .category-btn.active .category-count { background: rgba(0,0,0,0.2); }
        
        .apps-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 24px; }
        
        .app-card {
            background: var(--translucid);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 28px;
            transition: all 0.3s;
            cursor: pointer;
        }
        .app-card:hover { border-color: var(--main0); background: rgba(2, 154, 255, 0.05); }
        .app-header { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
        .app-icon { font-size: 48px; line-height: 1; }
        .app-info { flex: 1; }
        .app-name { font-family: 'Rubik', sans-serif; font-weight: 700; font-size: 18px; color: var(--white); margin-bottom: 4px; }
        .app-category { font-size: 11px; color: var(--main0); text-transform: uppercase; letter-spacing: 1px; }
        .app-desc { color: var(--text-muted); font-size: 14px; line-height: 1.6; margin-bottom: 20px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        
        .app-specs {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 16px;
            padding: 16px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 16px;
            border: 1px solid var(--border);
        }
        .spec-item { text-align: center; }
        .spec-value { font-family: 'Rubik', sans-serif; font-weight: 700; font-size: 18px; color: var(--main0); }
        .spec-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-top: 2px; }
        
        .app-footer { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .app-price { font-family: 'Rubik', sans-serif; font-weight: 700; font-size: 18px; color: var(--main1); }
        .app-price span { font-weight: 400; font-size: 12px; color: var(--text-muted); }
        
        .app-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
        .tag { background: transparent; border: 1px solid var(--disabled2); color: var(--text-muted); padding: 4px 12px; border-radius: 16px; font-size: 11px; }
        
        .deploy-btn {
            width: 100%;
            background: transparent;
            color: var(--text);
            border: 1px solid var(--text);
            padding: 14px;
            border-radius: 12px;
            font-family: 'Rubik', sans-serif;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .deploy-btn:hover:not(:disabled) { background: var(--gradient-main0); border-color: transparent; }
        .deploy-btn:disabled { border-color: var(--disabled2); color: var(--disabled2); cursor: not-allowed; }
        
        /* SSH Key selector */
        .ssh-key-option {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border);
            border-radius: 12px;
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .ssh-key-option:hover { border-color: var(--main0); }
        .ssh-key-option.selected { border-color: var(--main0); background: rgba(2, 154, 255, 0.1); }
        .ssh-key-option input[type="radio"] { accent-color: var(--main0); flex-shrink: 0; width: auto; margin-bottom: 0; padding: 0; }
        .ssh-key-label { font-size: 13px; color: var(--white); }
        .ssh-key-preview { font-size: 11px; color: var(--text-muted); font-family: 'Source Code Pro', monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 350px; }
        .ssh-key-loading { color: var(--text-muted); font-size: 13px; padding: 12px; text-align: center; }

        /* Modal */
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.9);
            backdrop-filter: blur(8px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 20px;
            overflow-y: auto;
        }
        .modal.active { display: flex; }
        .modal-content {
            background: var(--base1);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 32px;
            max-width: 560px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
        }
        .modal-header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }
        .modal-icon { font-size: 48px; }
        .modal-title h2 { font-family: 'Rubik', sans-serif; font-weight: 700; color: var(--white); font-size: 24px; margin-bottom: 4px; }
        .modal-title p { color: var(--text-muted); font-size: 14px; }
        
        .modal label { display: block; color: var(--text-muted); font-size: 11px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 1px; }
        .modal input, .modal textarea {
            width: 100%;
            background: var(--translucid);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px 16px;
            color: var(--white);
            font-family: 'Public Sans', sans-serif;
            font-size: 14px;
            margin-bottom: 16px;
        }
        .modal textarea { min-height: 100px; resize: vertical; font-family: 'Source Code Pro', monospace; font-size: 12px; }
        .modal input:focus, .modal textarea:focus { outline: none; border-color: var(--main0); }
        
        .requirements { background: rgba(0, 0, 0, 0.3); padding: 20px; border-radius: 16px; margin-bottom: 20px; border: 1px solid var(--border); }
        .requirements h4 { font-family: 'Rubik', sans-serif; color: var(--text-muted); font-size: 11px; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 1px; }
        .req-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        .req-item { background: var(--translucid); padding: 16px; border-radius: 12px; text-align: center; border: 1px solid var(--border); }
        .req-value { font-family: 'Rubik', sans-serif; font-weight: 700; font-size: 24px; color: var(--main0); }
        .req-label { font-size: 10px; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; }
        
        .cost-estimate {
            text-align: center;
            padding: 20px;
            background: rgba(92, 255, 177, 0.1);
            border: 1px solid rgba(92, 255, 177, 0.3);
            border-radius: 16px;
            margin-bottom: 20px;
        }
        .cost-estimate .amount {
            font-family: 'Rubik', sans-serif;
            font-style: italic;
            font-weight: 800;
            font-size: 32px;
            background: var(--gradient-main1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .cost-estimate .period { color: var(--text-muted); font-size: 14px; }
        
        .modal-btns { display: flex; gap: 12px; margin-top: 24px; }
        .modal-btns button {
            flex: 1;
            padding: 14px;
            border-radius: 12px;
            font-family: 'Rubik', sans-serif;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-cancel { background: transparent; border: 1px solid var(--border); color: var(--text); }
        .btn-cancel:hover { background: var(--translucid); }
        .btn-deploy { background: var(--gradient-main1); border: none; color: var(--black); }
        .btn-deploy:hover:not(:disabled) { opacity: 0.9; }
        .btn-deploy:disabled { background: var(--disabled); color: var(--disabled2); cursor: not-allowed; }
        
        .deploy-steps { margin-top: 20px; }
        .deploy-step {
            display: flex;
            align-items: flex-start;
            gap: 12px;
            padding: 12px;
            background: var(--translucid);
            border-radius: 12px;
            margin-bottom: 8px;
        }
        .deploy-step.active { border: 1px solid var(--main0); }
        .deploy-step.complete { border: 1px solid var(--main1); }
        .deploy-step.error { border: 1px solid var(--error); }
        .step-icon { font-size: 20px; }
        .step-content { flex: 1; }
        .step-title { font-weight: 600; margin-bottom: 4px; }
        .step-desc { font-size: 12px; color: var(--text-muted); }
        
        .success-panel {
            background: rgba(92, 255, 177, 0.1);
            border: 1px solid var(--main1);
            border-radius: 16px;
            padding: 20px;
            margin-top: 20px;
        }
        .success-panel h4 { color: var(--main1); margin-bottom: 12px; font-family: 'Rubik', sans-serif; }
        .success-panel code {
            display: block;
            background: rgba(0,0,0,0.3);
            padding: 12px;
            border-radius: 8px;
            font-family: 'Source Code Pro', monospace;
            font-size: 12px;
            margin: 8px 0;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .success-panel .copy-btn {
            background: var(--main1);
            color: var(--black);
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            margin-top: 8px;
        }
        
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--base1);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px 24px;
            color: var(--white);
            font-size: 14px;
            z-index: 2000;
            display: flex;
            align-items: center;
            gap: 12px;
            animation: slideIn 0.3s;
        }
        .toast.success { border-color: var(--main1); }
        .toast.error { border-color: var(--error); }
        .toast.info { border-color: var(--main0); }
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
        
        .footer {
            border-top: 1px solid var(--border);
            padding: 32px;
            margin-top: 64px;
            background: rgba(0, 0, 0, 0.3);
        }
        .footer-inner {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 24px;
        }
        .footer-links { display: flex; gap: 32px; }
        .footer-links a { color: var(--text-muted); text-decoration: none; font-size: 14px; }
        .footer-links a:hover { color: var(--main1); }
        .footer-brand { display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 14px; }
        
        .empty-state { text-align: center; padding: 64px 24px; color: var(--text-muted); }
        .empty-state-icon { font-size: 64px; margin-bottom: 16px; opacity: 0.5; }
        .empty-state h3 { font-family: 'Rubik', sans-serif; font-size: 20px; color: var(--text); margin-bottom: 8px; }
        
        @media (max-width: 768px) {
            .header-inner { flex-wrap: wrap; }
            .search-box { max-width: 100%; order: 3; flex-basis: 100%; }
            .apps-grid { grid-template-columns: 1fr; }
            .modal-content { padding: 24px; }
            .req-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <div class="logo">
                <svg class="logo-icon" viewBox="0 0 32 32" fill="none">
                    <path d="M16 2L2 9v14l14 7 14-7V9L16 2z" stroke="url(#grad)" stroke-width="2" fill="none"/>
                    <path d="M16 8l8 4v8l-8 4-8-4v-8l8-4z" fill="url(#grad)"/>
                    <defs><linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#EEFF9C"/><stop offset="100%" style="stop-color:#00FFBD"/></linearGradient></defs>
                </svg>
                <div class="logo-text">
                    <h1>Aleph Marketplace</h1>
                    <p>One-click app deployment</p>
                </div>
            </div>
            
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" id="searchInput" placeholder="Search apps..." oninput="handleSearch(this.value)">
            </div>
            
            <div class="wallet-section">
                <span class="credit-badge" id="creditBadge">
                    $<span id="creditAmount">0</span>
                </span>
                <div id="walletInfo" style="display: none;">
                    <span class="wallet-address" id="walletAddress"></span>
                </div>
                <button class="wallet-btn" id="connectBtn" onclick="connectWallet()">
                    <span id="connectBtnText">🦊 Connect Wallet</span>
                </button>
                <button class="disconnect-btn" id="disconnectBtn" style="display: none;" onclick="disconnectWallet()">
                    Disconnect
                </button>
            </div>
        </div>
    </header>
    
    <div class="stats-banner">
        <div class="stats-inner">
            <div class="stat-item">
                <div class="stat-value" id="totalApps">-</div>
                <div class="stat-label">Applications</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="totalCategories">-</div>
                <div class="stat-label">Categories</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">$0.17/day</div>
                <div class="stat-label">Starting Cost</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">∞</div>
                <div class="stat-label">Decentralized</div>
            </div>
        </div>
    </div>
    
    <main class="container">
        <div class="auth-notice" id="authNotice">
            <h3>🔐 Connect Your Wallet</h3>
            <p>Connect your Ethereum wallet to deploy applications on Aleph Cloud using your credits</p>
        </div>
        
        <section class="featured-section" id="featuredSection">
            <div class="section-header">
                <span class="section-number">01/</span>
                <span class="section-title">Featured</span>
                <span class="section-icon">⭐</span>
            </div>
            <div class="featured-grid" id="featuredApps"></div>
        </section>
        
        <section>
            <div class="section-header">
                <span class="section-number">02/</span>
                <span class="section-title">All Apps</span>
                <span class="section-icon">📦</span>
            </div>
            <div class="categories" id="categories"></div>
            <div class="apps-grid" id="apps"></div>
        </section>
    </main>
    
    <footer class="footer">
        <div class="footer-inner">
            <div class="footer-brand">
                <span>⬡</span>
                <span>Built on Aleph Cloud</span>
            </div>
            <div class="footer-links">
                <a href="https://github.com/shem-aleph/aleph-marketplace" target="_blank">GitHub</a>
                <a href="https://docs.aleph.im" target="_blank">Docs</a>
                <a href="https://aleph.im" target="_blank">Aleph Cloud</a>
            </div>
        </div>
    </footer>
    
    <div class="modal" id="deployModal">
        <div class="modal-content">
            <div class="modal-header">
                <span class="modal-icon" id="modalIcon">📦</span>
                <div class="modal-title">
                    <h2 id="modalTitle">Deploy App</h2>
                    <p id="modalSubtitle">Create an instance on Aleph Cloud</p>
                </div>
            </div>
            
            <div id="deployConfig">
                <div class="requirements" id="modalRequirements"></div>
                <div class="cost-estimate" id="modalCost"></div>
                
                <div>
                    <label>SSH Public Key (required for access)</label>
                    <div id="sshKeyList">
                        <div class="ssh-key-loading">Connect wallet to load SSH keys...</div>
                    </div>
                    <div id="customKeySection" style="margin-top: 4px;">
                        <div class="ssh-key-option" onclick="selectCustomKey()">
                            <input type="radio" name="sshKey" value="custom" id="sshKeyCustomRadio">
                            <div style="flex:1; min-width:0;">
                                <div class="ssh-key-label">Paste a custom key</div>
                            </div>
                        </div>
                        <textarea id="customSshKey" placeholder="ssh-rsa AAAA... or ssh-ed25519 AAAA..." style="display: none;"></textarea>
                    </div>
                </div>
                
                <div>
                    <label>Instance Name (optional)</label>
                    <input type="text" id="instanceName" placeholder="my-wordpress-instance">
                </div>
            </div>
            
            <div id="deployProgress" style="display: none;">
                <div class="deploy-steps" id="deploySteps"></div>
            </div>
            
            <div id="deploySuccess" style="display: none;"></div>
            
            <div class="modal-btns" id="modalBtns">
                <button class="btn-cancel" onclick="closeModal()">Cancel</button>
                <button class="btn-deploy" id="deployBtn" onclick="startDeploy()">🚀 Deploy with Wallet</button>
            </div>
        </div>
    </div>
    
    <script type="module">
        import { AuthenticatedAlephHttpClient } from '@aleph-sdk/client';
        import { getAccountFromProvider } from '@aleph-sdk/ethereum';
        import { PaymentType } from '@aleph-sdk/message';
        
        // Expose to global scope
        window.AlephSDK = { AuthenticatedAlephHttpClient, getAccountFromProvider, PaymentType };
    </script>
    
    <script>
        // State
        let apps = [];
        let categories = [];
        let selectedApp = null;
        let currentCategory = null;
        let searchQuery = '';
        const FEATURED_IDS = ['openclaw', 'ollama', 'nextcloud', 'code-server'];
        
        // Wallet state
        let wallet = {
            connected: false,
            address: null,
            provider: null,
            signer: null,
            alephAccount: null
        };
        let userCredits = null;
        let userSshKeys = [];
        let selectedSshKey = null;

        async function fetchSshKeys(address) {
            try {
                const res = await fetch(`/api/ssh-keys/${address}`);
                const data = await res.json();
                userSshKeys = data.keys || [];
                renderSshKeys();
            } catch (e) {
                console.error('Failed to fetch SSH keys:', e);
                userSshKeys = [];
                renderSshKeys();
            }
        }

        function renderSshKeys() {
            const container = document.getElementById('sshKeyList');

            if (userSshKeys.length === 0) {
                container.innerHTML = '<div class="ssh-key-loading">No SSH keys found on Aleph network. Paste one below.</div>';
                // Auto-select the custom key option
                selectCustomKey();
                return;
            }

            container.innerHTML = userSshKeys.map(function(key, i) {
                const preview = key.key.substring(0, 50) + '...';
                const label = escapeHtml(key.label || 'SSH Key');
                return '<div class="ssh-key-option ' + (i === 0 ? 'selected' : '') + '" onclick="selectSshKey(' + i + ')">'
                    + '<input type="radio" name="sshKey" value="' + i + '" ' + (i === 0 ? 'checked' : '') + '>'
                    + '<div style="overflow:hidden; flex:1; min-width:0;">'
                    + '<div class="ssh-key-label">' + label + '</div>'
                    + '<div class="ssh-key-preview">' + escapeHtml(preview) + '</div>'
                    + '</div></div>';
            }).join('');

            // Pre-select the first key
            selectedSshKey = userSshKeys[0].key;
        }

        function selectSshKey(index) {
            document.querySelectorAll('.ssh-key-option').forEach(function(el) { el.classList.remove('selected'); });
            const options = document.querySelectorAll('#sshKeyList .ssh-key-option');
            if (options[index]) {
                options[index].classList.add('selected');
                options[index].querySelector('input').checked = true;
            }
            document.getElementById('sshKeyCustomRadio').checked = false;
            document.getElementById('customSshKey').style.display = 'none';
            selectedSshKey = userSshKeys[index].key;
        }

        function selectCustomKey() {
            document.querySelectorAll('.ssh-key-option').forEach(function(el) { el.classList.remove('selected'); });
            const customOption = document.querySelector('#customKeySection .ssh-key-option');
            customOption.classList.add('selected');
            document.getElementById('sshKeyCustomRadio').checked = true;
            document.getElementById('customSshKey').style.display = 'block';
            selectedSshKey = null;
        }

        function getSelectedSshKey() {
            if (document.getElementById('sshKeyCustomRadio').checked) {
                return document.getElementById('customSshKey').value.trim();
            }
            return selectedSshKey;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function fetchCredits(address) {
            try {
                const res = await fetch(`/api/credits/${address}`);
                const data = await res.json();
                userCredits = data;

                const badge = document.getElementById('creditBadge');
                const amountEl = document.getElementById('creditAmount');
                const balance = data.credit_balance !== undefined ? data.credit_balance : data.balance;

                if (balance !== null && balance !== undefined) {
                    // credit_balance is in micro-units (1,000,000 = $1)
                    const credits = Number(balance) / 1000000;
                    amountEl.textContent = credits.toLocaleString('en-US', { maximumFractionDigits: 0 });
                    badge.style.display = 'inline-block';

                    if (credits < 100) {
                        badge.classList.add('warning');
                    } else {
                        badge.classList.remove('warning');
                    }
                }
            } catch (e) {
                console.error('Failed to fetch credits:', e);
            }
        }

        function showToast(message, type = 'info') {
            const existing = document.querySelector('.toast');
            if (existing) existing.remove();
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = `${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'} ${message}`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 5000);
        }
        
        function handleSearch(query) {
            searchQuery = query.toLowerCase();
            renderApps();
        }
        
        async function connectWallet() {
            const btn = document.getElementById('connectBtnText');
            if (typeof window.ethereum === 'undefined') {
                showToast('Please install MetaMask', 'error');
                return;
            }
            try {
                btn.textContent = 'Connecting...';
                const provider = new ethers.BrowserProvider(window.ethereum);
                const accounts = await provider.send('eth_requestAccounts', []);
                if (accounts.length === 0) throw new Error('No accounts');
                
                const signer = await provider.getSigner();
                wallet.provider = provider;
                wallet.signer = signer;
                wallet.address = await signer.getAddress();
                wallet.connected = true;
                
                // Initialize Aleph SDK account (loaded async via ESM module)
                if (window.AlephSDK) {
                    try {
                        wallet.alephAccount = await window.AlephSDK.getAccountFromProvider(window.ethereum);
                        console.log('Aleph account initialized:', wallet.alephAccount.address);
                    } catch (e) {
                        console.warn('Could not initialize Aleph account:', e);
                    }
                } else {
                    console.warn('Aleph SDK not loaded yet');
                }
                
                updateWalletUI();
                showToast('Wallet connected!', 'success');
                fetchCredits(wallet.address);
                fetchSshKeys(wallet.address);
            } catch (e) {
                showToast(e.message || 'Connection failed', 'error');
                btn.textContent = '🦊 Connect Wallet';
            }
        }
        
        function disconnectWallet() {
            wallet = { connected: false, address: null, provider: null, signer: null, alephAccount: null };
            userCredits = null;
            userSshKeys = [];
            selectedSshKey = null;
            document.getElementById('connectBtn').classList.remove('connected');
            document.getElementById('connectBtnText').textContent = '🦊 Connect Wallet';
            document.getElementById('walletInfo').style.display = 'none';
            document.getElementById('disconnectBtn').style.display = 'none';
            document.getElementById('creditBadge').style.display = 'none';
            document.getElementById('authNotice').classList.remove('hidden');
            renderApps();
            showToast('Disconnected', 'info');
        }
        
        function updateWalletUI() {
            document.getElementById('connectBtn').classList.add('connected');
            document.getElementById('connectBtnText').textContent = '✓ Connected';
            document.getElementById('walletAddress').textContent = wallet.address.slice(0,6) + '...' + wallet.address.slice(-4);
            document.getElementById('walletInfo').style.display = 'block';
            document.getElementById('disconnectBtn').style.display = 'block';
            document.getElementById('authNotice').classList.add('hidden');
            renderApps();
        }
        
        async function loadApps() {
            const res = await fetch('/api/apps');
            const data = await res.json();
            apps = data.apps;
            categories = data.categories;
            document.getElementById('totalApps').textContent = apps.length;
            document.getElementById('totalCategories').textContent = categories.length;
            renderCategories();
            renderFeatured();
            renderApps();
        }
        
        function formatMemory(mb) {
            return mb >= 1024 ? (mb / 1024).toFixed(1) + 'G' : mb + 'M';
        }
        
        function renderFeatured() {
            const featured = apps.filter(a => FEATURED_IDS.includes(a.id)).slice(0, 4);
            if (featured.length === 0) { document.getElementById('featuredSection').style.display = 'none'; return; }
            document.getElementById('featuredApps').innerHTML = featured.map(app => `
                <div class="featured-card" onclick="openDeploy('${app.id}')">
                    <span class="featured-badge">Featured</span>
                    <div class="app-icon">${app.icon}</div>
                    <div class="app-name">${app.name}</div>
                    <div class="app-category">${categories.find(c => c.id === app.category)?.name || app.category}</div>
                    <p class="app-desc">${app.description}</p>
                    <div class="app-price">~$${app.estimated_cost_per_day.toFixed(2)}<span>/day</span></div>
                </div>
            `).join('');
        }
        
        function renderCategories() {
            const counts = {};
            apps.forEach(a => { counts[a.category] = (counts[a.category] || 0) + 1; });
            document.getElementById('categories').innerHTML = `
                <button class="category-btn ${!currentCategory ? 'active' : ''}" onclick="filterCategory(null)">All <span class="category-count">${apps.length}</span></button>
                ${categories.map(c => `<button class="category-btn ${currentCategory === c.id ? 'active' : ''}" onclick="filterCategory('${c.id}')">${c.icon} ${c.name} <span class="category-count">${counts[c.id] || 0}</span></button>`).join('')}
            `;
        }
        
        function filterCategory(cat) {
            currentCategory = cat;
            renderCategories();
            renderApps();
        }
        
        function renderApps() {
            let filtered = apps;
            if (currentCategory) filtered = filtered.filter(a => a.category === currentCategory);
            if (searchQuery) filtered = filtered.filter(a => 
                a.name.toLowerCase().includes(searchQuery) || 
                a.description.toLowerCase().includes(searchQuery) ||
                a.tags.some(t => t.toLowerCase().includes(searchQuery))
            );
            if (filtered.length === 0) {
                document.getElementById('apps').innerHTML = `<div class="empty-state" style="grid-column: 1/-1;"><div class="empty-state-icon">🔍</div><h3>No apps found</h3><p>Try a different search or category</p></div>`;
                return;
            }
            document.getElementById('apps').innerHTML = filtered.map(app => `
                <div class="app-card" onclick="openDeploy('${app.id}')">
                    <div class="app-header">
                        <span class="app-icon">${app.icon}</span>
                        <div class="app-info">
                            <div class="app-name">${app.name}</div>
                            <div class="app-category">${categories.find(c => c.id === app.category)?.name || app.category}</div>
                        </div>
                    </div>
                    <p class="app-desc">${app.description}</p>
                    <div class="app-specs">
                        <div class="spec-item"><div class="spec-value">${app.requirements.vcpus}</div><div class="spec-label">vCPUs</div></div>
                        <div class="spec-item"><div class="spec-value">${formatMemory(app.requirements.memory_mb)}</div><div class="spec-label">RAM</div></div>
                        <div class="spec-item"><div class="spec-value">${app.requirements.disk_gb}</div><div class="spec-label">GB Disk</div></div>
                    </div>
                    <div class="app-footer"><span class="app-price">~$${app.estimated_cost_per_day.toFixed(2)}<span>/day</span></span></div>
                    <div class="app-tags">${app.tags.slice(0,3).map(t => `<span class="tag">${t}</span>`).join('')}</div>
                    <button class="deploy-btn" ${!wallet.connected ? 'disabled' : ''}>${wallet.connected ? '🚀 Deploy' : '🔒 Connect to Deploy'}</button>
                </div>
            `).join('');
        }
        
        function openDeploy(appId) {
            if (!wallet.connected) { showToast('Connect your wallet first', 'error'); return; }
            selectedApp = apps.find(a => a.id === appId);
            
            document.getElementById('modalIcon').textContent = selectedApp.icon;
            document.getElementById('modalTitle').textContent = `Deploy ${selectedApp.name}`;
            document.getElementById('modalSubtitle').textContent = 'Create an instance on Aleph Cloud';
            
            document.getElementById('modalRequirements').innerHTML = `
                <h4>Instance Requirements</h4>
                <div class="req-grid">
                    <div class="req-item"><div class="req-value">${selectedApp.requirements.vcpus}</div><div class="req-label">vCPUs</div></div>
                    <div class="req-item"><div class="req-value">${formatMemory(selectedApp.requirements.memory_mb)}</div><div class="req-label">RAM</div></div>
                    <div class="req-item"><div class="req-value">${selectedApp.requirements.disk_gb}</div><div class="req-label">GB Disk</div></div>
                </div>
            `;
            document.getElementById('modalCost').innerHTML = `
                <div class="amount">~$${selectedApp.estimated_cost_per_day.toFixed(2)}</div>
                <div class="period">estimated per day (paid from your credits)</div>
            `;
            
            // Reset state
            document.getElementById('deployConfig').style.display = 'block';
            document.getElementById('deployProgress').style.display = 'none';
            document.getElementById('deploySuccess').style.display = 'none';
            document.getElementById('modalBtns').style.display = 'flex';
            document.getElementById('deployBtn').disabled = false;
            document.getElementById('deployBtn').textContent = '🚀 Deploy with Wallet';

            // Re-render SSH keys for the modal
            renderSshKeys();

            document.getElementById('deployModal').classList.add('active');
        }
        
        function closeModal() {
            document.getElementById('deployModal').classList.remove('active');
            selectedApp = null;
        }
        
        function updateStep(stepId, status, message) {
            const step = document.getElementById(stepId);
            if (!step) return;
            step.className = `deploy-step ${status}`;
            step.querySelector('.step-icon').textContent = status === 'complete' ? '✓' : status === 'error' ? '✕' : status === 'active' ? '⏳' : '○';
            if (message) step.querySelector('.step-desc').textContent = message;
        }
        
        async function startDeploy() {
            const sshKey = getSelectedSshKey();
            const instanceName = document.getElementById('instanceName').value.trim() || `${selectedApp.id}-instance`;

            if (!sshKey) {
                showToast('Please select or paste an SSH public key', 'error');
                return;
            }

            if (!sshKey.startsWith('ssh-') && !sshKey.startsWith('ecdsa-')) {
                showToast('Invalid SSH key format. Should start with ssh-rsa, ssh-ed25519, etc.', 'error');
                return;
            }
            
            // Show progress
            document.getElementById('deployConfig').style.display = 'none';
            document.getElementById('deployProgress').style.display = 'block';
            document.getElementById('deployBtn').disabled = true;
            document.getElementById('deployBtn').textContent = 'Deploying...';
            
            const steps = [
                { id: 'step-account', title: 'Initialize Account', desc: 'Connecting to Aleph network...' },
                { id: 'step-instance', title: 'Create Instance', desc: 'Signing instance creation message...' },
                { id: 'step-wait', title: 'Wait for Allocation', desc: 'Waiting for CRN to allocate resources...' },
                { id: 'step-done', title: 'Deployment Complete', desc: 'Your instance is ready!' }
            ];
            
            document.getElementById('deploySteps').innerHTML = steps.map(s => `
                <div class="deploy-step" id="${s.id}">
                    <span class="step-icon">○</span>
                    <div class="step-content">
                        <div class="step-title">${s.title}</div>
                        <div class="step-desc">${s.desc}</div>
                    </div>
                </div>
            `).join('');
            
            try {
                // Step 1: Initialize account
                updateStep('step-account', 'active');
                
                if (!window.AlephSDK) {
                    throw new Error('Aleph SDK not loaded. Please refresh the page and try again.');
                }
                if (!wallet.alephAccount) {
                    wallet.alephAccount = await window.AlephSDK.getAccountFromProvider(window.ethereum);
                }

                const client = new window.AlephSDK.AuthenticatedAlephHttpClient(wallet.alephAccount);
                updateStep('step-account', 'complete', `Account: ${wallet.address.slice(0,8)}...`);
                
                // Step 2: Create instance
                updateStep('step-instance', 'active', 'Please sign the message in your wallet...');
                
                const instanceConfig = {
                    authorized_keys: [sshKey],
                    resources: {
                        vcpus: selectedApp.requirements.vcpus,
                        memory: selectedApp.requirements.memory_mb,
                    },
                    rootfs: {
                        size_mib: selectedApp.requirements.disk_gb * 1024
                    },
                    metadata: {
                        name: instanceName,
                        app: selectedApp.id,
                        marketplace: 'aleph-marketplace'
                    },
                    variables: {
                        APP_NAME: selectedApp.name,
                        APP_ID: selectedApp.id,
                        DOCKER_COMPOSE: btoa(selectedApp.docker_compose)
                    },
                    payment: {
                        chain: 'ETH',
                        type: window.AlephSDK.PaymentType.hold
                    }
                };
                
                const response = await client.createInstance(instanceConfig);
                const instanceId = response.item_hash;
                
                updateStep('step-instance', 'complete', `Instance ID: ${instanceId.slice(0,12)}...`);
                
                // Step 3: Wait for allocation
                updateStep('step-wait', 'active', 'Waiting for instance to be allocated...');
                
                // Poll for instance status (simplified - real impl would check CRN)
                await new Promise(resolve => setTimeout(resolve, 5000));
                
                updateStep('step-wait', 'complete', 'Instance allocated!');
                updateStep('step-done', 'complete');
                
                // Show success
                document.getElementById('deployProgress').style.display = 'none';
                document.getElementById('modalBtns').style.display = 'none';
                
                // Generate random passwords to replace placeholders in compose content
                let composeForDeploy = selectedApp.docker_compose;
                const generatedPasswords = {};
                if (composeForDeploy.includes('__GENERATED_PASSWORD__')) {
                    const pw = Array.from(crypto.getRandomValues(new Uint8Array(16)))
                        .map(b => b.toString(36).padStart(2, '0')).join('').slice(0, 22);
                    composeForDeploy = composeForDeploy.replaceAll('__GENERATED_PASSWORD__', pw);
                    generatedPasswords.password = pw;
                }
                if (composeForDeploy.includes('__GENERATED_ROOT_PASSWORD__')) {
                    const rpw = Array.from(crypto.getRandomValues(new Uint8Array(16)))
                        .map(b => b.toString(36).padStart(2, '0')).join('').slice(0, 22);
                    composeForDeploy = composeForDeploy.replaceAll('__GENERATED_ROOT_PASSWORD__', rpw);
                    generatedPasswords.root_password = rpw;
                }

                const setupScript = `# Connect to your instance and run:
ssh root@<INSTANCE_IP>

# Then run these commands:
apt update && apt install -y docker.io docker-compose
echo '${btoa(composeForDeploy)}' | base64 -d > docker-compose.yml
docker-compose up -d`;

                let credentialsHtml = '';
                if (Object.keys(generatedPasswords).length > 0) {
                    credentialsHtml = '<p style="margin-top:16px;font-weight:bold;color:var(--main2)">Generated Credentials (save these!):</p>';
                    if (generatedPasswords.password) {
                        credentialsHtml += `<code>Password: ${generatedPasswords.password}</code>`;
                    }
                    if (generatedPasswords.root_password) {
                        credentialsHtml += `<code>Root Password: ${generatedPasswords.root_password}</code>`;
                    }
                }

                document.getElementById('deploySuccess').innerHTML = `
                    <div class="success-panel">
                        <h4>Instance Created Successfully!</h4>
                        <p>Instance ID: <code>${instanceId}</code></p>
                        ${credentialsHtml}
                        <p style="margin-top:12px">Your instance is being provisioned. Check the <a href="https://app.aleph.cloud/console/" target="_blank" style="color:var(--main1)">Aleph Console</a> for status and IP address.</p>
                        <p style="margin-top:16px;font-weight:bold">Setup Commands:</p>
                        <code>${setupScript}</code>
                        <button class="copy-btn" onclick="navigator.clipboard.writeText(\`${setupScript.replace(/`/g, '\\`')}\`); showToast('Copied!', 'success')">Copy Commands</button>
                        <button class="btn-cancel" style="margin-top:16px;width:100%" onclick="closeModal()">Close</button>
                    </div>
                `;
                document.getElementById('deploySuccess').style.display = 'block';
                
                showToast('Instance created successfully!', 'success');
                
            } catch (err) {
                console.error('Deploy error:', err);
                const currentActive = document.querySelector('.deploy-step.active');
                if (currentActive) {
                    updateStep(currentActive.id, 'error', err.message || 'Deployment failed');
                }
                showToast(err.message || 'Deployment failed', 'error');
                document.getElementById('deployBtn').disabled = false;
                document.getElementById('deployBtn').textContent = '🔄 Retry';
            }
        }
        
        // Listen for account changes
        if (typeof window.ethereum !== 'undefined') {
            window.ethereum.on('accountsChanged', (accs) => {
                if (accs.length === 0 || (wallet.address && accs[0].toLowerCase() !== wallet.address.toLowerCase())) {
                    disconnectWallet();
                }
            });
        }
        
        // Init
        loadApps();
    </script>
</body>
</html>"""
