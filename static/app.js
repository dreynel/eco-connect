const state = {
  rates: {},
  material: "plastic_bottle",
  remainingSeconds: 0,
  isConnected: false,
  pausedSeconds: 0,
  activeUntil: 0,
  serverTime: 0,
  clientFetchTime: 0,
  insert_locked_by_other: false,
  insert_locked_by_me: false,
};

const remainingTime = document.querySelector("#remainingTime");
const connectionState = document.querySelector("#connectionState");
const statusPanel = document.querySelector("#statusPanel");
const connectionActions = document.querySelector("#connectionActions");
const sizeGrid = document.querySelector("#sizeGrid");
const ratesGrid = document.querySelector("#ratesGrid");
const topupNotice = document.querySelector("#topupNotice");
const connectButton = document.querySelector("#connectButton");
const pauseButton = document.querySelector("#pauseButton");
const insertButton = document.querySelector("#insertButton");
const ratesButton = document.querySelector("#ratesButton");
const insertPanel = document.querySelector("#insertPanel");
const ratesPanel = document.querySelector("#ratesPanel");
const cancelInsertButton = document.querySelector("#cancelInsertButton");
const resetButton = document.querySelector("#resetButton");
const confirmModal = document.querySelector("#confirmModal");
const confirmCancelBtn = document.querySelector("#confirmCancelBtn");
const confirmOkBtn = document.querySelector("#confirmOkBtn");
const connectionToast = document.querySelector("#connectionToast");
const toastTitle = document.querySelector("#toastTitle");
const toastDesc = document.querySelector("#toastDesc");
const toastActionContainer = document.querySelector("#toastActionContainer");
const statusDetails = document.querySelector("#statusDetails");
const expirationTime = document.querySelector("#expirationTime");

let lastConnectedState = null;
let toastTimeout;

function showToast(type) {
  clearTimeout(toastTimeout);
  if (!connectionToast || !toastTitle || !toastDesc || !toastActionContainer) return;

  if (type === "online") {
    toastTitle.innerHTML = `🟢 Internet Connected`;
    toastDesc.textContent = "Your internet access is active. You can now close this login screen and use all your apps.";
    toastActionContainer.innerHTML = `<a href="http://www.google.com" class="toast-btn">Go to Google</a>`;
    connectionToast.classList.add("is-visible");
    toastTimeout = setTimeout(() => {
      connectionToast.classList.remove("is-visible");
    }, 8000);
  } else if (type === "offline") {
    toastTitle.innerHTML = `🔴 Internet Paused`;
    toastDesc.textContent = "Your internet time has expired or been paused. Please insert recyclable materials to get more time.";
    toastActionContainer.innerHTML = "";
    connectionToast.classList.add("is-visible");
    toastTimeout = setTimeout(() => {
      connectionToast.classList.remove("is-visible");
    }, 5000);
  } else {
    connectionToast.classList.remove("is-visible");
  }
}

const materialToast = document.querySelector("#materialToast");
const materialToastDesc = document.querySelector("#materialToastDesc");
let materialToastTimeout;

function showMaterialToast(materialLabel, sizeLabel, minutesAdded) {
  clearTimeout(materialToastTimeout);
  if (!materialToast || !materialToastDesc) return;

  materialToastDesc.innerHTML = `
    Inserted <strong>${materialLabel} (${sizeLabel})</strong><br>
    Added <strong>+${minutesAdded} min</strong> to your balance!
  `;
  materialToast.classList.add("is-visible");

  materialToastTimeout = setTimeout(() => {
    materialToast.classList.remove("is-visible");
  }, 4000);
}


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

function renderTimer() {
  const hasTime = state.remainingSeconds > 0 || state.isConnected;

  statusPanel.classList.toggle("is-hidden", !hasTime);
  connectionActions.classList.toggle("is-hidden", !hasTime);
  remainingTime.textContent = formatDuration(state.remainingSeconds);
  remainingTime.classList.toggle("has-time", hasTime);
  connectionState.textContent = state.isConnected ? "Connected" : "Paused";
  connectionState.classList.toggle("is-connected", state.isConnected);
  connectButton.disabled = state.isConnected || state.remainingSeconds <= 0;
  pauseButton.disabled = !state.isConnected;
  if (resetButton) {
    resetButton.disabled = state.remainingSeconds <= 0 && !state.isConnected;
  }

  // Handle active session details display
  if (state.remainingSeconds > 0) {
    statusDetails.classList.remove("is-hidden");
    
    let activeRemaining = 0;
    let expirationDate = null;

    if (state.isConnected && state.activeUntil && state.serverTime && state.clientFetchTime) {
      // Calculate active remaining time
      const elapsedSeconds = Math.floor((Date.now() - state.clientFetchTime) / 1000);
      const currentServerTime = state.serverTime + elapsedSeconds;
      activeRemaining = Math.max(0, state.activeUntil - currentServerTime);
      expirationDate = new Date(state.activeUntil * 1000);
    } else {
      // Paused state details (capped at 1 hour/3600s)
      activeRemaining = Math.min(state.remainingSeconds, 3600);
      expirationDate = null;
    }
    
    
    if (expirationDate) {
      expirationTime.textContent = expirationDate.toLocaleString([], { 
        month: 'short',
        day: 'numeric',
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit',
        hour12: true
      });
    } else {
      expirationTime.textContent = "Paused";
    }
  } else {
    statusDetails.classList.add("is-hidden");
  }

  if (state.insert_locked_by_me) {
    insertButton.style.display = "none";
    if (insertPanel.classList.contains("is-hidden")) {
      showPanel("insert");
    }
  } else if (state.insert_locked_by_other) {
    insertButton.style.display = "";
    insertButton.disabled = true;
    insertButton.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
      </svg>
      Machine in use...
    `;
    if (!insertPanel.classList.contains("is-hidden")) {
      showPanel("");
    }
  } else {
    insertButton.style.display = "";
    insertButton.disabled = false;
    insertButton.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="23 4 23 10 17 10"></polyline>
        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
      </svg>
      Insert Recyclables
    `;
    if (!insertPanel.classList.contains("is-hidden")) {
      showPanel("");
    }
  }

  // Trigger connection status toasts on transition
  if (lastConnectedState !== null && lastConnectedState !== state.isConnected) {
    if (state.isConnected) {
      showToast("online");
    } else {
      showToast("offline");
    }
  }
  lastConnectedState = state.isConnected;
}

function updateSessionState(data) {
  state.remainingSeconds = data.remaining_seconds;
  state.isConnected = data.is_connected;
  state.insert_locked_by_other = data.insert_locked_by_other;
  state.insert_locked_by_me = data.insert_locked_by_me;
  state.activeUntil = data.active_until;
  state.pausedSeconds = data.paused_seconds;
  state.serverTime = data.server_time;
  state.clientFetchTime = Date.now();
  renderTimer();
}

function renderSizes() {
  const materialRates = state.rates[state.material];
  if (!materialRates) return;

  sizeGrid.innerHTML = "";
  Object.entries(materialRates.sizes).forEach(([size, item]) => {
    const button = document.createElement("button");
    button.className = "size-button";
    button.type = "button";
    button.dataset.size = size;

    const sizeScale = size === "large" ? "scale(1.25)" : size === "medium" ? "scale(1.05)" : "scale(0.85)";
    const itemSvg = state.material === "plastic_bottle"
      ? `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transform: ${sizeScale}; transition: transform 0.3s; margin-bottom: 4px; color: var(--primary);">
          <path d="M10 2h4v3h-4zM8 9a4 4 0 0 1 4-4h0a4 4 0 0 1 4 4v11a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2zM9 9h6M9 13h6M9 17h6"/>
        </svg>`
      : `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transform: ${sizeScale}; transition: transform 0.3s; margin-bottom: 4px; color: var(--primary);">
          <ellipse cx="12" cy="5" rx="5" ry="2.5"/>
          <path d="M7 5v14c0 1.38 2.24 2.5 5 2.5s5-1.12 5-2.5V5"/>
          <ellipse cx="12" cy="19" rx="5" ry="2.5"/>
        </svg>`;

    button.innerHTML = `
      ${itemSvg}
      <span>${item.label}</span>
      <strong>${item.minutes} min</strong>
    `;
    button.addEventListener("click", () => topUp(size));
    sizeGrid.append(button);
  });
}

function renderRates() {
  ratesGrid.innerHTML = "";
  Object.entries(state.rates).forEach(([key, material]) => {
    const block = document.createElement("article");
    block.className = "rate-block";
    
    const headerSvg = key === "plastic_bottle"
      ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10 2h4v3h-4zM8 9a4 4 0 0 1 4-4h0a4 4 0 0 1 4 4v11a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2zM9 9h6M9 13h6M9 17h6"/>
        </svg>`
      : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <ellipse cx="12" cy="5" rx="5" ry="2.5"/>
          <path d="M7 5v14c0 1.38 2.24 2.5 5 2.5s5-1.12 5-2.5V5"/>
          <ellipse cx="12" cy="19" rx="5" ry="2.5"/>
        </svg>`;

    block.innerHTML = `
      <h2>${headerSvg} ${material.label}</h2>
      <dl>
        ${Object.values(material.sizes)
          .map(
            (item) => `
              <div>
                <dt>${item.label}</dt>
                <dd>${item.minutes} min</dd>
              </div>
            `
          )
          .join("")}
      </dl>
    `;
    ratesGrid.append(block);
  });
}

function showPanel(name) {
  const showInsert = name === "insert";
  const showRates = name === "rates";
  insertPanel.classList.toggle("is-hidden", !showInsert);
  ratesPanel.classList.toggle("is-hidden", !showRates);
  insertButton.classList.toggle("is-active", showInsert);
  ratesButton.classList.toggle("is-active", showRates);

  if (showInsert && state.remainingSeconds <= 0) {
    topupNotice.textContent = "Waiting for recyclable material...";
  }
}

async function loadRates() {
  const response = await fetch("/api/rates");
  const data = await response.json();
  state.rates = data.rates;
  renderSizes();
  renderRates();
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  updateSessionState(data);
}

async function postAction(path) {
  const response = await fetch(path, { method: "POST" });
  const data = await response.json();

  if (!response.ok) {
    topupNotice.textContent = data.error || "Request failed.";
    return;
  }

  updateSessionState(data);

  if (path === "/api/connect" && state.isConnected) {
    const userAgent = navigator.userAgent.toLowerCase();
    if (userAgent.includes("android")) {
      window.location.href = "http://connectivitycheck.gstatic.com/generate_204";
    } else if (userAgent.includes("iphone") || userAgent.includes("ipad") || userAgent.includes("macintosh")) {
      window.location.href = "http://captive.apple.com/hotspot-detect.html";
    } else {
      window.location.href = "http://www.msftconnecttest.com/connecttest.txt";
    }
  } else if (path === "/api/pause" && !state.isConnected) {
    window.location.href = "http://connectivitycheck.gstatic.com/generate_204";
  }
}

async function topUp(size) {
  topupNotice.textContent = "";
  const response = await fetch("/api/topup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ material: state.material, size }),
  });
  const data = await response.json();

  if (!response.ok) {
    topupNotice.textContent = data.error || "Top-up failed.";
    return;
  }

  updateSessionState(data);
  
  // Trigger floating toast notification for material insertion
  showMaterialToast(data.material_label, data.size_label, data.minutes_added);
  
  topupNotice.textContent = `${data.material_label} ${data.size_label}: +${data.minutes_added} minutes saved`;
}

document.querySelectorAll(".material-button").forEach((button) => {
  button.addEventListener("click", () => {
    state.material = button.dataset.material;
    document.querySelectorAll(".material-button").forEach((item) => {
      item.classList.toggle("is-active", item === button);
    });
    topupNotice.textContent = "";
    renderSizes();
  });
});

connectButton.addEventListener("click", () => postAction("/api/connect"));
pauseButton.addEventListener("click", () => postAction("/api/pause"));
if (resetButton && confirmModal && confirmCancelBtn && confirmOkBtn) {
  resetButton.addEventListener("click", () => {
    confirmModal.classList.remove("is-hidden");
  });

  confirmCancelBtn.addEventListener("click", () => {
    confirmModal.classList.add("is-hidden");
  });

  confirmOkBtn.addEventListener("click", () => {
    confirmModal.classList.add("is-hidden");
    postAction("/api/reset");
  });

  // Close modal if user clicks the backdrop
  confirmModal.addEventListener("click", (e) => {
    if (e.target === confirmModal) {
      confirmModal.classList.add("is-hidden");
    }
  });
}
insertButton.addEventListener("click", async () => {
  if (insertPanel.classList.contains("is-hidden")) {
    const response = await fetch("/api/insert/start", { method: "POST" });
    if (response.ok) {
      showPanel("insert");
      loadStatus();
    } else {
      const data = await response.json();
      alert(data.detail || "Cannot start insertion right now.");
    }
  } else {
    showPanel("");
  }
});
cancelInsertButton.addEventListener("click", async () => {
  await fetch("/api/insert/cancel", { method: "POST" });
  showPanel("");
  loadStatus();
});
ratesButton.addEventListener("click", () => showPanel("rates"));

setInterval(() => {
  if (state.remainingSeconds > 0) {
    if (state.isConnected) {
      const elapsedSeconds = Math.floor((Date.now() - state.clientFetchTime) / 1000);
      const currentServerTime = state.serverTime + elapsedSeconds;
      const activeRemaining = Math.max(0, state.activeUntil - currentServerTime);
      
      state.remainingSeconds = activeRemaining + (state.pausedSeconds || 0);
      
      if (activeRemaining <= 0) {
        state.isConnected = false;
        window.location.href = "http://connectivitycheck.gstatic.com/generate_204";
      }
    }
    renderTimer();
  }
}, 1000);

loadRates();
loadStatus();
setInterval(loadStatus, 2000);
