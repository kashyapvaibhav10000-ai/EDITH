#!/usr/bin/env python3
"""
EDITH Dev Panel — patch_devpanel_final.py
Run once: python3 patch_devpanel_final.py
Backup created at dashboard.py.bak before any changes.
"""

import os, shutil, sys

DASH = os.path.expanduser("~/EDITH/dashboard.py")

if not os.path.exists(DASH):
    sys.exit(f"✗ Not found: {DASH}")

shutil.copy(DASH, DASH + ".bak")
print(f"✓ Backup → {DASH}.bak")

with open(DASH) as f:
    src = f.read()

errors = []

# ════════════════════════════════════════════════════════════════
# PATCH 1 — Add nav item under MENU after Phone (not after Commands)
# ════════════════════════════════════════════════════════════════
NAV_OLD = '<div class="nav-item"><span class="ni">📱</span> Phone</div>'
NAV_NEW = '<div class="nav-item"><span class="ni">📱</span> Phone</div>\n    <div class="nav-item" id="nav-devpanel"><span class="ni">🧠</span> Dev Panel</div>'

if NAV_OLD in src:
    src = src.replace(NAV_OLD, NAV_NEW, 1)
    print("✓ Patch 1: Dev Panel nav item added under MENU after Phone")
else:
    errors.append("Patch 1 FAILED: Phone nav-item not found — check emoji/spacing")

# ════════════════════════════════════════════════════════════════
# PATCH 2 — Inject Dev Panel HTML overlay before </body>
# ════════════════════════════════════════════════════════════════
DEV_HTML = '''
  <!-- ══ DEV PANEL ══════════════════════════════════════════════ -->
  <div id="dp-overlay" style="display:none;position:fixed;top:0;left:210px;right:0;bottom:0;background:var(--bg);overflow-y:auto;z-index:50;padding:28px 32px">

    <div style="font-family:'Orbitron',monospace;font-size:15px;color:var(--gold);margin-bottom:24px;letter-spacing:3px;text-shadow:0 0 20px var(--gold-dim);display:flex;align-items:center;gap:12px">
      🧠 DEV PANEL — SELF-AWARENESS MODULE
      <span id="dp-status" style="font-size:9px;letter-spacing:2px;color:var(--text-dim);font-family:'Rajdhani',sans-serif;margin-left:auto"></span>
    </div>

    <!-- Module chips -->
    <div class="card" style="margin-bottom:16px">
      <div class="card-label">Context Scope — select modules to load</div>
      <div id="dp-chips" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;min-height:32px">
        <span style="color:var(--text-dim);font-size:11px">Loading modules...</span>
      </div>
      <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
        <button onclick="dpSelectAll()" style="font-size:10px;padding:3px 12px;background:#0f0f18;border:1px solid var(--border);color:var(--text);cursor:pointer;font-family:'Share Tech Mono',monospace;letter-spacing:1px">ALL</button>
        <button onclick="dpClearAll()" style="font-size:10px;padding:3px 12px;background:#0f0f18;border:1px solid var(--border);color:var(--text);cursor:pointer;font-family:'Share Tech Mono',monospace;letter-spacing:1px">CLEAR</button>
        <span id="dp-ctx-info" style="font-size:10px;color:var(--text-dim);font-family:'Rajdhani',sans-serif;letter-spacing:1px"></span>
      </div>
    </div>

    <!-- Mode tabs -->
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <button class="dp-mode-btn" data-mode="qa" id="dpbtn-qa"
        style="padding:5px 16px;font-size:10px;letter-spacing:1px;border:1px solid var(--gold);background:#1a120a;color:var(--gold);cursor:pointer;font-family:'Share Tech Mono',monospace"
        onclick="dpSetMode(this)">Q &amp; A</button>
      <button class="dp-mode-btn" data-mode="council" id="dpbtn-council"
        style="padding:5px 16px;font-size:10px;letter-spacing:1px;border:1px solid var(--border);background:#0a0a0f;color:var(--text-dim);cursor:pointer;font-family:'Share Tech Mono',monospace"
        onclick="dpSetMode(this)">⚔ COUNCIL</button>
      <button class="dp-mode-btn" data-mode="next" id="dpbtn-next"
        style="padding:5px 16px;font-size:10px;letter-spacing:1px;border:1px solid var(--border);background:#0a0a0f;color:var(--text-dim);cursor:pointer;font-family:'Share Tech Mono',monospace"
        onclick="dpSetMode(this)">🔮 WHAT NEXT</button>
    </div>

    <!-- Input -->
    <div class="card" style="margin-bottom:16px">
      <div class="card-label">Query</div>
      <textarea id="dp-input" rows="4"
        placeholder="Ask EDITH about her own architecture...  (Ctrl+Enter to submit)"
        style="width:100%;background:#050507;border:1px solid var(--border);color:var(--text);padding:10px 12px;font-family:'Share Tech Mono',monospace;font-size:12px;resize:vertical;outline:none;margin-top:8px;line-height:1.6"
        onkeydown="if(event.ctrlKey&&event.key==='Enter')dpSubmit()"></textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px">
        <span style="font-size:10px;color:var(--text-dim);font-family:'Rajdhani',sans-serif">Ctrl+Enter to submit</span>
        <button id="dp-btn" onclick="dpSubmit()"
          style="padding:6px 24px;background:var(--gold);color:#000;font-weight:700;border:none;cursor:pointer;font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:11px">
          QUERY
        </button>
      </div>
    </div>

    <!-- Response -->
    <div class="card">
      <div class="card-label" style="display:flex;justify-content:space-between">
        Response
        <span id="dp-resp-meta" style="font-size:9px;color:var(--text-dim);font-family:'Rajdhani',sans-serif;letter-spacing:1px;font-weight:400"></span>
      </div>
      <div id="dp-response"
        style="min-height:140px;font-size:12px;line-height:1.8;white-space:pre-wrap;margin-top:8px;color:var(--text)">
        <span style="color:var(--text-dim)">Awaiting query...</span>
      </div>
    </div>

  </div>
  <!-- ══ END DEV PANEL ══════════════════════════════════════════ -->
'''

BODY_CLOSE = '</body>\n</html>"""'
if BODY_CLOSE in src:
    src = src.replace(BODY_CLOSE, DEV_HTML + BODY_CLOSE, 1)
    print("✓ Patch 2: Dev Panel HTML injected")
else:
    errors.append("Patch 2 FAILED: '</body>\\n</html>\"\"\"' anchor not found")

# ════════════════════════════════════════════════════════════════
# PATCH 3 — Replace nav-item JS (section switcher + full dev panel logic)
# ════════════════════════════════════════════════════════════════
OLD_NAV_JS = """document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
  });
});"""

NEW_NAV_JS = """// ── Dev Panel state ─────────────────────────────────────────────
let dpMode = 'qa';
let dpModules = [];
let dpSelected = new Set();
let dpInited = false;

async function dpInit() {
  if (dpInited) return;
  dpInited = true;
  document.getElementById('dp-status').textContent = 'LOADING MODULES...';
  try {
    const r = await fetch('/api/devpanel/modules');
    const data = await r.json();
    dpModules = data.modules;
    const container = document.getElementById('dp-chips');
    container.innerHTML = '';
    dpModules.forEach(m => {
      const chip = document.createElement('div');
      chip.textContent = m.name;
      chip.title = m.lines + ' lines';
      chip.style.cssText = 'padding:3px 10px;font-size:10px;border:1px solid var(--border);cursor:pointer;border-radius:10px;color:var(--text-dim);user-select:none;transition:all 0.15s;font-family:Share Tech Mono,monospace';
      chip.dataset.name = m.name;
      chip.addEventListener('click', () => {
        if (dpSelected.has(m.name)) {
          dpSelected.delete(m.name);
          chip.style.borderColor = 'var(--border)';
          chip.style.color = 'var(--text-dim)';
          chip.style.background = '';
        } else {
          dpSelected.add(m.name);
          chip.style.borderColor = 'var(--gold)';
          chip.style.color = 'var(--gold)';
          chip.style.background = 'var(--gold-glow)';
        }
        dpUpdateCtx();
      });
      container.appendChild(chip);
    });
    document.getElementById('dp-status').textContent = dpModules.length + ' MODULES READY';
    dpUpdateCtx();
  } catch(e) {
    document.getElementById('dp-status').textContent = 'ERROR LOADING MODULES';
    document.getElementById('dp-chips').innerHTML = '<span style="color:var(--red);font-size:11px">Failed to load modules — is dashboard.py running?</span>';
  }
}

function dpUpdateCtx() {
  const total = dpModules.filter(m => dpSelected.has(m.name)).reduce((s,m) => s + m.lines, 0);
  const el = document.getElementById('dp-ctx-info');
  if (el) el.textContent = dpSelected.size + ' files selected · ~' + total + ' lines in context';
}

function dpSelectAll() {
  dpSelected.clear();
  document.querySelectorAll('#dp-chips div').forEach((chip, i) => {
    if (!dpModules[i]) return;
    dpSelected.add(dpModules[i].name);
    chip.style.borderColor = 'var(--gold)';
    chip.style.color = 'var(--gold)';
    chip.style.background = 'var(--gold-glow)';
  });
  dpUpdateCtx();
}

function dpClearAll() {
  dpSelected.clear();
  document.querySelectorAll('#dp-chips div').forEach(chip => {
    chip.style.borderColor = 'var(--border)';
    chip.style.color = 'var(--text-dim)';
    chip.style.background = '';
  });
  dpUpdateCtx();
}

function dpSetMode(btn) {
  dpMode = btn.dataset.mode;
  document.querySelectorAll('.dp-mode-btn').forEach(b => {
    b.style.borderColor = 'var(--border)';
    b.style.background = '#0a0a0f';
    b.style.color = 'var(--text-dim)';
  });
  btn.style.borderColor = 'var(--gold)';
  btn.style.background = '#1a120a';
  btn.style.color = 'var(--gold)';
}

async function dpSubmit() {
  const query = document.getElementById('dp-input').value.trim();
  if (!query) return;
  if (dpSelected.size === 0) {
    document.getElementById('dp-response').innerHTML = '<span style="color:var(--gold)">⚠ Select at least one module first.</span>';
    return;
  }
  const btn  = document.getElementById('dp-btn');
  const resp = document.getElementById('dp-response');
  const meta = document.getElementById('dp-resp-meta');
  btn.disabled = true;
  btn.textContent = '...';
  btn.style.opacity = '0.6';
  resp.innerHTML = '<span style="color:var(--gold)">⟳ Processing — this may take up to 60s...</span>';
  meta.textContent = '';
  const t0 = Date.now();
  try {
    const r = await fetch('/api/devpanel/query', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ query, mode: dpMode, files: Array.from(dpSelected) })
    });
    const data = await r.json();
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    resp.textContent = data.response || data.error || JSON.stringify(data);
    meta.textContent = 'mode:' + dpMode + ' · ' + dpSelected.size + ' files · ' + elapsed + 's';
  } catch(e) {
    resp.innerHTML = '<span style="color:var(--red)">✗ Error: ' + e.message + '</span>';
  }
  btn.disabled = false;
  btn.textContent = 'QUERY';
  btn.style.opacity = '1';
}

// ── Nav item switching ──────────────────────────────────────────
document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    const overlay = document.getElementById('dp-overlay');
    if (el.id === 'nav-devpanel') {
      overlay.style.display = 'block';
      dpInit();
    } else {
      overlay.style.display = 'none';
    }
  });
});"""

if OLD_NAV_JS in src:
    src = src.replace(OLD_NAV_JS, NEW_NAV_JS, 1)
    print("✓ Patch 3: Nav JS replaced with section switcher + full Dev Panel logic")
else:
    errors.append("Patch 3 FAILED: nav-item JS block not found — likely whitespace mismatch")

# ════════════════════════════════════════════════════════════════
# PATCH 4 — Add FastAPI endpoints before if __name__ == "__main__"
# ════════════════════════════════════════════════════════════════
MAIN_ANCHOR = 'if __name__ == "__main__":'

NEW_ENDPOINTS = '''
# ══════════════════════════════════════════════════════════════════
# DEV PANEL API
# ══════════════════════════════════════════════════════════════════
import glob as _glob
import asyncio as _asyncio
import urllib.request as _urlreq
import json as _json2

_EDITH_DIR         = os.path.expanduser("~/EDITH")
_CHAT_URL          = "http://localhost:8001/api/chat"
_MAX_CHARS_PER_FILE = 4000
_MAX_FILES          = 8

_SYSTEM_QA = (
    "You are EDITH's self-awareness module with full access to her source code. "
    "Answer architecture and development questions accurately and concisely. "
    "Reference specific function names, classes, and line details when relevant."
)

_SYSTEM_COUNCIL = """You are EDITH's Council of Minds. Four internal personas analyse the question and debate.

STRATEGIST — long-term architecture, scalability, design principles
CRITIC      — flaws, edge cases, tech debt, failure modes
BUILDER     — concrete next steps, exact code actions needed
FUTURIST    — ambitious possibilities, what EDITH could become

Respond in this exact format (no preamble):
STRATEGIST: <2-3 sentences>
CRITIC: <2-3 sentences>
BUILDER: <2-3 sentences>
FUTURIST: <2-3 sentences>
CONSENSUS: <1-2 sentences final verdict>"""

_SYSTEM_NEXT = (
    "You are EDITH's self-awareness module. Based on the provided codebase, "
    "identify the single most impactful next thing to build. "
    "Be specific: module name, key functions to write, why it matters most right now. "
    "No generic advice — ground everything in the actual code provided."
)


@app.get("/api/devpanel/modules")
async def devpanel_modules():
    modules = []
    for fp in sorted(_glob.glob(os.path.join(_EDITH_DIR, "*.py"))):
        name = os.path.basename(fp)
        try:
            with open(fp) as fh:
                lines = sum(1 for _ in fh)
        except Exception:
            lines = 0
        modules.append({"name": name, "lines": lines})
    return {"modules": modules}


@app.post("/api/devpanel/query")
async def devpanel_query(req: Request):
    body  = await req.json()
    query = body.get("query", "").strip()
    mode  = body.get("mode", "qa")
    files = body.get("files", [])[:_MAX_FILES]

    if not query:
        return {"error": "Empty query."}

    ctx_parts = []
    for fname in files:
        fp = os.path.join(_EDITH_DIR, fname)
        try:
            with open(fp) as fh:
                raw = fh.read()[:_MAX_CHARS_PER_FILE]
            ctx_parts.append(f"=== {fname} ===\\n{raw}")
        except Exception:
            pass

    context  = "\\n\\n".join(ctx_parts) if ctx_parts else "(no files loaded)"
    system   = {
        "qa":      _SYSTEM_QA,
        "council": _SYSTEM_COUNCIL,
        "next":    _SYSTEM_NEXT,
    }.get(mode, _SYSTEM_QA)

    full_msg = (
        f"[SYSTEM ROLE]\\n{system}\\n\\n"
        f"[CODEBASE CONTEXT]\\n{context}\\n\\n"
        f"[QUESTION]\\n{query}"
    )

    def _call():
        payload = _json2.dumps({"message": full_msg}).encode()
        rq = _urlreq.Request(
            _CHAT_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with _urlreq.urlopen(rq, timeout=90) as r:
            return _json2.loads(r.read())

    try:
        data   = await _asyncio.get_event_loop().run_in_executor(None, _call)
        answer = (
            data.get("response")
            or data.get("message")
            or data.get("text")
            or str(data)
        )
    except Exception as e:
        answer = (
            f"[ERROR — could not reach chat_server at {_CHAT_URL}]\\n"
            f"{type(e).__name__}: {e}\\n\\n"
            f"Make sure chat_server.py is running:\\n"
            f"  cd ~/EDITH && source ~/edith-env/bin/activate && python chat_server.py &"
        )

    return {"response": answer}


'''

if MAIN_ANCHOR in src:
    src = src.replace(MAIN_ANCHOR, NEW_ENDPOINTS + MAIN_ANCHOR, 1)
    print("✓ Patch 4: FastAPI endpoints added")
else:
    errors.append("Patch 4 FAILED: 'if __name__ == \"__main__\":' not found")

# ════════════════════════════════════════════════════════════════
# Write or abort
# ════════════════════════════════════════════════════════════════
if errors:
    print("\n⚠ ERRORS — dashboard.py NOT modified (backup safe):")
    for e in errors:
        print("  •", e)
    print("\nFix: paste the failing anchor text from your dashboard.py and I'll update the script.")
    sys.exit(1)

with open(DASH, "w") as f:
    f.write(src)

print("""
✅ ALL 4 PATCHES APPLIED

Restart dashboard:
  pkill -f 'uvicorn.*8000'; pkill -f 'python.*dashboard'
  cd ~/EDITH && source ~/edith-env/bin/activate && python dashboard.py &

Open: http://localhost:8000
Click: 🧠 Dev Panel (under Phone in sidebar)

Rollback if broken:
  cp ~/EDITH/dashboard.py.bak ~/EDITH/dashboard.py
""")
