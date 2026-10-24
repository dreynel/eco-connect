const loginPanel = document.querySelector("#loginPanel");
const dashboardPanel = document.querySelector("#dashboardPanel");
const loginForm = document.querySelector("#loginForm");
const loginNotice = document.querySelector("#loginNotice");
const logoutButton = document.querySelector("#logoutButton");
const refreshButton = document.querySelector("#refreshButton");
const statsGrid = document.querySelector("#statsGrid");
const breakdownBody = document.querySelector("#breakdownBody");
const recentBody = document.querySelector("#recentBody");
const sessionsBody = document.querySelector("#sessionsBody");

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
  }

  return `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
}

function formatTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleString([], {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  });
}

function setAuthenticated(authenticated) {
  loginPanel.classList.toggle("is-hidden", authenticated);
  dashboardPanel.classList.toggle("is-hidden", !authenticated);
  logoutButton.classList.toggle("is-hidden", !authenticated);
  
  const defaultHeader = document.querySelector(".admin-header");
  if (defaultHeader) {
    defaultHeader.classList.toggle("is-hidden", authenticated);
  }
  
  if (authenticated) {
    loadRates();
    loadBlacklist();
  } else {
    document.body.classList.remove("sidebar-open");
  }
}

function emptyRow(colspan, text) {
  return `<tr><td class="empty-cell" colspan="${colspan}">${text}</td></tr>`;
}

function renderDashboard(data) {
  const { summary, breakdown, recent_topups: recentTopups, sessions } = data;

  statsGrid.innerHTML = `
    <article class="stat-card">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--primary); margin-bottom: 8px;">
        <polyline points="21 8 21 21 3 21 3 8"></polyline>
        <rect x="1" y="3" width="22" height="5"></rect>
        <line x1="10" y1="12" x2="14" y2="12"></line>
      </svg>
      <span>Total Items</span>
      <strong>${summary.item_count}</strong>
    </article>
    <article class="stat-card">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--amber); margin-bottom: 8px;">
        <circle cx="12" cy="12" r="10"></circle>
        <polyline points="12 6 12 12 16 14"></polyline>
      </svg>
      <span>Total Minutes</span>
      <strong>${summary.total_minutes}</strong>
    </article>
    <article class="stat-card">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: #60a5fa; margin-bottom: 8px;">
        <path d="M5 12.55a11 11 0 0 1 14.08 0"></path>
        <path d="M1.42 9a16 16 0 0 1 21.16 0"></path>
        <path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
        <line x1="12" y1="20" x2="12.01" y2="20" stroke-width="3"></line>
      </svg>
      <span>Connected</span>
      <strong>${summary.active_clients}</strong>
    </article>
    <article class="stat-card">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: #c084fc; margin-bottom: 8px;">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="10" y1="15" x2="10" y2="9"></line>
        <line x1="14" y1="15" x2="14" y2="9"></line>
      </svg>
      <span>Saved Time</span>
      <strong>${summary.saved_clients}</strong>
    </article>
  `;

  breakdownBody.innerHTML = breakdown.length
    ? breakdown
        .map(
          (item) => `
            <tr>
              <td>${item.material_label}</td>
              <td>${item.size_label}</td>
              <td>${item.count}</td>
              <td>${item.minutes} min</td>
            </tr>
          `
        )
        .join("")
    : emptyRow(4, "No materials inserted yet.");

  recentBody.innerHTML = recentTopups.length
    ? recentTopups
        .map(
          (item) => `
            <tr>
              <td>${formatTime(item.created_at)}</td>
              <td>${item.client_ip}</td>
              <td>${item.material_label}</td>
              <td>${item.size_label}</td>
              <td>${item.minutes_added} min</td>
            </tr>
          `
        )
        .join("")
    : emptyRow(5, "No recent insertions.");

  sessionsBody.innerHTML = sessions.length
    ? sessions
        .map(
          (item) => `
            <tr>
              <td>${item.client_ip}</td>
              <td>
                <span class="badge ${item.is_connected ? 'badge-connected' : 'badge-paused'}">
                  ${item.is_connected ? 'Connected' : 'Paused'}
                </span>
              </td>
              <td>${formatDuration(item.remaining_seconds)}</td>
            </tr>
          `
        )
        .join("")
    : emptyRow(3, "No active or saved client sessions.");
}

async function loadRates() {
  try {
    const response = await fetch("/api/rates");
    if (!response.ok) return;
    const { rates } = await response.json();
    if (rates.plastic_bottle && rates.plastic_bottle.sizes) {
      document.querySelector("#rate_plastic_bottle_small").value = rates.plastic_bottle.sizes.small.minutes;
      document.querySelector("#rate_plastic_bottle_medium").value = rates.plastic_bottle.sizes.medium.minutes;
      document.querySelector("#rate_plastic_bottle_large").value = rates.plastic_bottle.sizes.large.minutes;
    }
    if (rates.metal_can && rates.metal_can.sizes) {
      document.querySelector("#rate_metal_can_small").value = rates.metal_can.sizes.small.minutes;
      document.querySelector("#rate_metal_can_medium").value = rates.metal_can.sizes.medium.minutes;
      document.querySelector("#rate_metal_can_large").value = rates.metal_can.sizes.large.minutes;
    }
  } catch (err) {
    console.error("Failed to load rates:", err);
  }
}

async function loadDashboard() {
  const response = await fetch("/api/admin/dashboard");

  if (response.status === 401) {
    setAuthenticated(false);
    return;
  }

  const data = await response.json();
  setAuthenticated(true);
  renderDashboard(data);
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginNotice.textContent = "";

  const response = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: document.querySelector("#usernameInput").value,
      password: document.querySelector("#passwordInput").value,
    }),
  });
  const data = await response.json();

  if (!response.ok) {
    loginNotice.textContent = data.error || "Login failed.";
    return;
  }

  setAuthenticated(true);
  await loadDashboard();
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/admin/logout", { method: "POST" });
  setAuthenticated(false);
});

refreshButton.addEventListener("click", loadDashboard);

const ratesForm = document.querySelector("#ratesForm");
ratesForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    rates: {
      plastic_bottle: {
        small: parseInt(document.querySelector("#rate_plastic_bottle_small").value, 10),
        medium: parseInt(document.querySelector("#rate_plastic_bottle_medium").value, 10),
        large: parseInt(document.querySelector("#rate_plastic_bottle_large").value, 10),
      },
      metal_can: {
        small: parseInt(document.querySelector("#rate_metal_can_small").value, 10),
        medium: parseInt(document.querySelector("#rate_metal_can_medium").value, 10),
        large: parseInt(document.querySelector("#rate_metal_can_large").value, 10),
      }
    }
  };

  try {
    const response = await fetch("/api/admin/rates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      alert("Rates updated successfully!");
      await loadRates();
      await loadDashboard();
    } else {
      const data = await response.json();
      alert("Failed to update rates: " + (data.detail || "Unknown error"));
    }
  } catch (err) {
    alert("Error saving rates: " + err.message);
  }
});

const resetDashboardBtn = document.querySelector("#resetDashboardBtn");
const resetModal = document.querySelector("#resetModal");
const resetCancelBtn = document.querySelector("#resetCancelBtn");
const resetOkBtn = document.querySelector("#resetOkBtn");

resetDashboardBtn.addEventListener("click", () => {
  resetModal.classList.remove("is-hidden");
});

resetCancelBtn.addEventListener("click", () => {
  resetModal.classList.add("is-hidden");
});

resetOkBtn.addEventListener("click", async () => {
  resetModal.classList.add("is-hidden");
  try {
    const response = await fetch("/api/admin/reset_dashboard", { method: "POST" });
    if (response.ok) {
      alert("Dashboard data reset successfully!");
      await loadDashboard();
    } else {
      const data = await response.json();
      alert("Reset failed: " + (data.detail || "Unknown error"));
    }
  } catch (err) {
    alert("Error resetting data: " + err.message);
  }
});

function escapeHtml(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}

async function loadBlacklist() {
  try {
    const response = await fetch("/api/admin/blacklist");
    if (!response.ok) return;
    const { blacklist } = await response.json();
    const blacklistList = document.querySelector("#blacklistList");
    
    if (!blacklist.length) {
      blacklistList.innerHTML = `<li class="blacklist-empty">No blacklisted websites.</li>`;
      return;
    }
    
    blacklistList.innerHTML = blacklist
      .map(
        (item) => `
          <li class="blacklist-item">
            <span>${escapeHtml(item.domain)}</span>
            <button class="blacklist-item-delete" data-domain="${escapeHtml(item.domain)}" title="Remove block">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </li>
        `
      )
      .join("");
      
    // Wire delete handlers
    blacklistList.querySelectorAll(".blacklist-item-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const domain = btn.getAttribute("data-domain");
        if (confirm(`Are you sure you want to remove ${domain} from the blacklist?`)) {
          await deleteBlacklist(domain);
        }
      });
    });
  } catch (err) {
    console.error("Failed to load blacklist:", err);
  }
}

async function addBlacklist(domain) {
  try {
    const response = await fetch("/api/admin/blacklist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain }),
    });
    if (response.ok) {
      document.querySelector("#blacklistInput").value = "";
      await loadBlacklist();
    } else {
      const data = await response.json();
      alert("Failed to block site: " + (data.detail || "Unknown error"));
    }
  } catch (err) {
    alert("Error blocking site: " + err.message);
  }
}

async function deleteBlacklist(domain) {
  try {
    const response = await fetch(`/api/admin/blacklist/${encodeURIComponent(domain)}`, {
      method: "DELETE",
    });
    if (response.ok) {
      await loadBlacklist();
    } else {
      const data = await response.json();
      alert("Failed to remove block: " + (data.detail || "Unknown error"));
    }
  } catch (err) {
    alert("Error removing block: " + err.message);
  }
}

const blacklistForm = document.querySelector("#blacklistForm");
blacklistForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const domain = document.querySelector("#blacklistInput").value.trim();
  if (domain) {
    await addBlacklist(domain);
  }
});

// Sidebar navigation and layout controller
const navItems = document.querySelectorAll(".sidebar-nav .nav-item");
const tabPanes = document.querySelectorAll(".tab-pane");
const currentTabTitle = document.querySelector("#currentTabTitle");

navItems.forEach((btn) => {
  btn.addEventListener("click", () => {
    const targetTabId = btn.getAttribute("data-tab");
    
    // Switch active states
    navItems.forEach((item) => item.classList.remove("active"));
    tabPanes.forEach((pane) => pane.classList.remove("active"));
    
    btn.classList.add("active");
    const targetPane = document.getElementById(targetTabId);
    if (targetPane) {
      targetPane.classList.add("active");
    }
    
    if (currentTabTitle) {
      currentTabTitle.textContent = btn.textContent.trim();
    }
    
    // Automatically close sidebar drawer on mobile after clicking
    document.body.classList.remove("sidebar-open");
  });
});

// Mobile burger menu and backdrop overlays
const sidebarToggle = document.querySelector("#sidebarToggle");
const sidebarOverlay = document.querySelector("#sidebarOverlay");

if (sidebarToggle) {
  sidebarToggle.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-open");
  });
}

if (sidebarOverlay) {
  sidebarOverlay.addEventListener("click", () => {
    document.body.classList.remove("sidebar-open");
  });
}

// Wire the sidebar logout button
const sidebarLogoutBtn = document.querySelector("#sidebarLogoutBtn");
if (sidebarLogoutBtn) {
  sidebarLogoutBtn.addEventListener("click", async () => {
    await fetch("/api/admin/logout", { method: "POST" });
    setAuthenticated(false);
  });
}

// Load everything on startup
loadDashboard();
setInterval(() => {
  if (!dashboardPanel.classList.contains("is-hidden")) {
    loadDashboard();
  }
}, 15000);
