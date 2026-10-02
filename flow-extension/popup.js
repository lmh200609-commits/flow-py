let detectedEmail = "";
let matchedTab = null;

// Helper: extract email from a tab's DOM
async function extractEmailFromTab(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tabId },
      func: () => {
        // Look for account button or aria-labels
        const elements = document.querySelectorAll('a[aria-label*="@"], button[aria-label*="@"], [aria-label*="Google 帐号"], [aria-label*="Google Account"], [aria-label*="Google 帳號"], [aria-label*="Google-Konto"]');
        for (const el of elements) {
          const label = el.getAttribute("aria-label") || "";
          const match = label.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
          if (match) return match[0];
        }
        // Search in page innerText
        const bodyText = document.body ? document.body.innerText : "";
        const match = bodyText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
        return match ? match[0] : null;
      }
    });
    if (results && results[0] && results[0].result) {
      return results[0].result;
    }
  } catch (e) {
    console.warn("Script execution failed on tab", tabId, e);
  }
  return null;
}

// 1. Detect Google account email across open tabs
async function detectAccountEmail() {
  const display = document.getElementById("email-display");
  const manualInput = document.getElementById("manual-email");

  try {
    // 1. Check active tab first
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (activeTab && activeTab.url && (activeTab.url.includes("flow.google.com") || activeTab.url.includes("google.com"))) {
      const email = await extractEmailFromTab(activeTab.id);
      if (email) {
        detectedEmail = email;
        matchedTab = activeTab;
        display.innerHTML = `<span style="color:#34d399; font-weight:bold;">👤 ${email}</span>`;
        manualInput.value = email;
        return;
      }
    }

    // 2. If not on active tab, search ALL open tabs for flow.google.com or google.com
    const allTabs = await chrome.tabs.query({});
    // Priority: flow.google.com tabs first
    const flowTabs = allTabs.filter(t => t.url && t.url.includes("flow.google.com"));
    const googleTabs = allTabs.filter(t => t.url && t.url.includes("google.com") && !t.url.includes("127.0.0.1"));
    const candidateTabs = [...flowTabs, ...googleTabs];

    for (const tab of candidateTabs) {
      if (tab.id) {
        const email = await extractEmailFromTab(tab.id);
        if (email) {
          detectedEmail = email;
          matchedTab = tab;
          display.innerHTML = `<span style="color:#34d399; font-weight:bold;">👤 ${email}</span> <span style="font-size:11px; color:#9ca3af;">(来自已打开标签页)</span>`;
          manualInput.value = email;
          return;
        }
      }
    }

    // 3. Fallback: prompt manual input
    display.innerHTML = `<span style="color:#fbbf24;">⚠️ 请在下方输入你的 Google 邮箱</span>`;
    manualInput.style.display = "block";
    manualInput.focus();
  } catch (err) {
    console.error("Detect error:", err);
    display.innerHTML = `<span style="color:#fbbf24;">请在下方输入此账号的 Google 邮箱</span>`;
    manualInput.style.display = "block";
  }
}

// 2. Click button to extract all cookies and send to local gateway
document.getElementById("btn-sync").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync");
  const statusDiv = document.getElementById("status");
  const manualInput = document.getElementById("manual-email");

  const emailToUse = (manualInput.value.trim() || detectedEmail || "").trim();
  if (!emailToUse) {
    statusDiv.className = "error";
    statusDiv.innerText = "请先输入或确认此账号对应的 Google 邮箱！";
    manualInput.style.display = "block";
    manualInput.focus();
    return;
  }

  btn.disabled = true;
  statusDiv.className = "";
  statusDiv.innerText = "⏳ 正在提取 Google 认证凭据与邮箱...";

  try {
    // Determine project URL
    let projectUrl = "https://flow.google.com/";
    if (matchedTab && matchedTab.url && matchedTab.url.includes("flow.google.com/project/")) {
      projectUrl = matchedTab.url;
    } else {
      const [cur] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (cur && cur.url && cur.url.includes("flow.google.com/project/")) {
        projectUrl = cur.url;
      }
    }

    // Query all cookies with domain ending with google.com
    const allCookies = await chrome.cookies.getAll({});
    const googleCookies = allCookies.filter(c => {
      const d = (c.domain || "").toLowerCase();
      return d.endsWith("google.com") || d.endsWith("googleusercontent.com");
    });

    const cookieMap = new Map();
    for (const c of googleCookies) {
      cookieMap.set(c.name + "@" + c.domain + "@" + c.path, {
        name: c.name,
        value: c.value,
        domain: c.domain,
        path: c.path,
        expires: c.expirationDate || -1,
        httpOnly: c.httpOnly,
        secure: c.secure,
        sameSite: c.sameSite === "no_restriction" ? "None" : (c.sameSite === "lax" ? "Lax" : "Strict")
      });
    }
    const cleanCookies = Array.from(cookieMap.values());

    if (cleanCookies.length === 0) {
      statusDiv.className = "error";
      statusDiv.innerText = "未在当前浏览器中找到 Google 登录状态！";
      btn.disabled = false;
      return;
    }

    // Post to local gateway
    const res = await fetch("http://127.0.0.1:8765/api/pool/import-cookies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_url: projectUrl,
        email: emailToUse,
        name: `Gemini Pro (${emailToUse})`,
        cookies: cleanCookies
      })
    });

    const data = await res.json();
    if (data.status === "ok") {
      statusDiv.className = "success";
      const accInfo = data.account ? `(${data.account.name || data.account.id})` : "";
      statusDiv.innerText = `🎉 授权成功！${emailToUse} 已同步入库！`;
    } else {
      statusDiv.className = "error";
      statusDiv.innerText = "导入失败: " + (data.message || "未知错误");
      btn.disabled = false;
    }
  } catch (err) {
    statusDiv.className = "error";
    statusDiv.innerText = "连接本地服务失败，请确保本地网关已启动！";
    btn.disabled = false;
  }
});

// Run detection on popup open
detectAccountEmail();
