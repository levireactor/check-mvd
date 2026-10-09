/**
 * Controller cho Popup UI Extension - Zalo Order Bot v2.2
 * Tự động bóc tách đơn, tự động quét hàng loạt tag,
 * VÀ TRA CỨU MÃ VẬN ĐƠN THEO SĐT TỪ SHEET + BÁO KHÁCH TỰ ĐỘNG.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Tab Controls
  const tabBtnOrders = document.getElementById('tab-btn-orders');
  const tabBtnMvd = document.getElementById('tab-btn-mvd');
  const tabContentOrders = document.getElementById('tab-content-orders');
  const tabContentMvd = document.getElementById('tab-content-mvd');

  // Common Header & Settings
  const inputApiKey = document.getElementById('input-api-key');
  const btnSaveKey = document.getElementById('btn-save-key');
  const settingsPanel = document.getElementById('settings-panel');
  const btnSettingsToggle = document.getElementById('btn-settings-toggle');
  const connStatusBar = document.getElementById('conn-status-bar');

  // Tab 1 Elements
  const toggleAutoCapture = document.getElementById('toggle-auto-capture');
  const inputTargetTag = document.getElementById('input-target-tag');
  const btnParseActive = document.getElementById('btn-parse-active');
  const btnAutoBatchScan = document.getElementById('btn-auto-batch-scan');
  const progressBox = document.getElementById('progress-box');
  const progressStatusText = document.getElementById('progress-status-text');
  const progressBarFill = document.getElementById('progress-bar-fill');
  const btnStopBatch = document.getElementById('btn-stop-batch');
  const orderListContainer = document.getElementById('order-list');
  const emptyState = document.getElementById('empty-state');
  const orderCountEl = document.getElementById('order-count');
  const btnExportCsv = document.getElementById('btn-export-csv');
  const btnClearAll = document.getElementById('btn-clear-all');
  const btnSyncToolPee = document.getElementById('btn-sync-tool-pee');

  // Tab 2: MVĐ Elements
  const sheetOrderCountEl = document.getElementById('sheet-order-count');
  const btnSyncSheetOrders = document.getElementById('btn-sync-sheet-orders');
  const inputSearchPhone = document.getElementById('input-search-phone');
  const btnDoSearchPhone = document.getElementById('btn-do-search-phone');
  const btnGetPhoneFromChat = document.getElementById('btn-get-phone-from-chat');
  const mvdResultCard = document.getElementById('mvd-result-card');
  const mvdEmptyHint = document.getElementById('mvd-empty-hint');
  const resCarrier = document.getElementById('res-carrier');
  const resMvd = document.getElementById('res-mvd');
  const resName = document.getElementById('res-name');
  const resPhone = document.getElementById('res-phone');
  const resStatus = document.getElementById('res-status');
  const resProduct = document.getElementById('res-product');
  const resCod = document.getElementById('res-cod');
  const resDriver = document.getElementById('res-driver');
  const rowProd = document.getElementById('row-prod');
  const rowCod = document.getElementById('row-cod');
  const rowDriver = document.getElementById('row-driver');
  const btnInsertZalo = document.getElementById('btn-insert-zalo');
  const btnCopyReply = document.getElementById('btn-copy-reply');

  // Status Bar
  const statusBar = document.getElementById('status-bar');
  const statusText = document.getElementById('status-text');

  let orders = [];
  let sheetOrders = [];
  let currentFoundOrder = null;

  // 1. Chuyển đổi Tab
  tabBtnOrders.onclick = () => {
    tabBtnOrders.classList.add('active');
    tabBtnMvd.classList.remove('active');
    tabContentOrders.classList.remove('hidden');
    tabContentMvd.classList.add('hidden');
  };

  tabBtnMvd.onclick = () => {
    tabBtnMvd.classList.add('active');
    tabBtnOrders.classList.remove('active');
    tabContentMvd.classList.remove('hidden');
    tabContentOrders.classList.add('hidden');
    updateSheetCountUI();
  };

  // 2. Tải cấu hình từ Storage
  const toggleBotReply = document.getElementById('toggle-bot-reply');
  const checkAutoSendDirect = document.getElementById('check-auto-send-direct');
  const checkOnlyTagged = document.getElementById('check-only-tagged');

  chrome.storage.local.get([
    'gemini_api_key', 'saved_orders', 'target_tag', 'auto_capture_enabled', 
    'tracking_sheet_orders', 'auto_reply_mvd_bot', 'auto_send_directly', 'only_reply_tagged_customers', 'sheet_api_url'
  ], (res) => {
    if (res.gemini_api_key) inputApiKey.value = res.gemini_api_key;
    if (res.sheet_api_url && document.getElementById('input-sheet-url')) {
      document.getElementById('input-sheet-url').value = res.sheet_api_url;
    }
    if (res.target_tag) {
      inputTargetTag.value = res.target_tag;
      const mvdTagEl = document.getElementById('input-mvd-tags');
      if (mvdTagEl) mvdTagEl.value = res.target_tag;
    }
    if (res.auto_capture_enabled !== undefined) {
      toggleAutoCapture.checked = !!res.auto_capture_enabled;
    } else {
      toggleAutoCapture.checked = true;
    }

    if (toggleBotReply) {
      toggleBotReply.checked = res.auto_reply_mvd_bot !== undefined ? !!res.auto_reply_mvd_bot : true;
    }
    if (checkAutoSendDirect) {
      checkAutoSendDirect.checked = res.auto_send_directly !== undefined ? !!res.auto_send_directly : true;
    }
    if (checkOnlyTagged) {
      checkOnlyTagged.checked = res.only_reply_tagged_customers !== undefined ? !!res.only_reply_tagged_customers : true;
    }

    if (res.saved_orders && Array.isArray(res.saved_orders)) {
      orders = res.saved_orders;
      renderOrders();
    }

    if (res.tracking_sheet_orders && Array.isArray(res.tracking_sheet_orders)) {
      sheetOrders = res.tracking_sheet_orders;
      updateSheetCountUI();
    } else {
      syncSheetData(false);
    }
  });

  if (toggleBotReply) {
    toggleBotReply.onchange = () => {
      chrome.storage.local.set({ auto_reply_mvd_bot: toggleBotReply.checked });
    };
  }
  if (checkAutoSendDirect) {
    checkAutoSendDirect.onchange = () => {
      chrome.storage.local.set({ auto_send_directly: checkAutoSendDirect.checked });
    };
  }
  if (checkOnlyTagged) {
    checkOnlyTagged.onchange = () => {
      chrome.storage.local.set({ only_reply_tagged_customers: checkOnlyTagged.checked });
    };
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local') {
      if (changes.saved_orders) {
        orders = changes.saved_orders.newValue || [];
        renderOrders();
      }
      if (changes.tracking_sheet_orders) {
        sheetOrders = changes.tracking_sheet_orders.newValue || [];
        updateSheetCountUI();
      }
    }
  });

  // Settings
  btnSettingsToggle.onclick = () => settingsPanel.classList.toggle('hidden');
  btnSaveKey.onclick = () => {
    const key = inputApiKey.value.trim();
    chrome.storage.local.set({ gemini_api_key: key }, () => {
      alert("Đã lưu API Key thành công!");
      settingsPanel.classList.add('hidden');
    });
  };

  const inputMvdTags = document.getElementById('input-mvd-tags');

  inputTargetTag.onchange = () => {
    const val = inputTargetTag.value.trim();
    if (inputMvdTags) inputMvdTags.value = val;
    chrome.storage.local.set({ target_tag: val });
  };

  if (inputMvdTags) {
    inputMvdTags.onchange = () => {
      const val = inputMvdTags.value.trim();
      inputTargetTag.value = val;
      chrome.storage.local.set({ target_tag: val });
    };
  }

  toggleAutoCapture.onchange = async () => {
    const isEnabled = toggleAutoCapture.checked;
    chrome.storage.local.set({ auto_capture_enabled: isEnabled });
    await sendToZaloTab({ action: "SET_AUTO_CAPTURE", enabled: isEnabled });
  };

  function setStatus(text, show = true) {
    if (show) {
      statusText.innerText = text;
      statusBar.classList.remove('hidden');
    } else {
      statusBar.classList.add('hidden');
    }
  }

  // 3. Tab Zalo Web Connection Helpers
  async function getZaloTab() {
    try {
      let tabs = await chrome.tabs.query({ url: "*://chat.zalo.me/*" });
      if (!tabs || tabs.length === 0) {
        const allTabs = await chrome.tabs.query({});
        tabs = allTabs.filter(t => t.url && t.url.includes("chat.zalo.me"));
      }
      if (!tabs || tabs.length === 0) return null;
      return tabs.find(t => t.active) || tabs[0];
    } catch (e) {
      return null;
    }
  }

  async function sendToZaloTab(message, allowInject = true) {
    const targetTab = await getZaloTab();
    if (!targetTab) return null;

    return new Promise((resolve) => {
      chrome.tabs.sendMessage(targetTab.id, message, async (response) => {
        if (chrome.runtime.lastError) {
          if (allowInject && chrome.scripting) {
            try {
              await chrome.scripting.executeScript({
                target: { tabId: targetTab.id },
                files: ["parser.js", "content.js"]
              });
              await chrome.scripting.insertCSS({
                target: { tabId: targetTab.id },
                files: ["floating_ui.css"]
              });
              setTimeout(() => {
                chrome.tabs.sendMessage(targetTab.id, message, (retryRes) => {
                  resolve(chrome.runtime.lastError ? null : retryRes);
                });
              }, 300);
              return;
            } catch (err) {}
          }
          resolve(null);
        } else {
          resolve(response);
        }
      });
    });
  }

  async function checkConnection() {
    const targetTab = await getZaloTab();
    if (!targetTab) {
      connStatusBar.className = "conn-status-bar disconnected";
      connStatusBar.innerHTML = `
        <span class="conn-dot"></span>
        <span>⚠️ Chưa mở Zalo Web. <a href="https://chat.zalo.me" target="_blank" style="color:#0068ff; font-weight:700;">Mở Zalo ngay</a></span>
      `;
      return;
    }

    const res = await sendToZaloTab({ action: "PING" });
    if (res && res.connected) {
      connStatusBar.className = "conn-status-bar connected";
      connStatusBar.innerHTML = `
        <span class="conn-dot"></span>
        <span>${res.currentChat ? `🟢 Đã kết nối tự động: [${res.currentChat}]` : `🟢 Đã kết nối tự động với Zalo Web`}</span>
      `;
    } else {
      connStatusBar.className = "conn-status-bar disconnected";
      connStatusBar.innerHTML = `
        <span class="conn-dot"></span>
        <span style="flex:1;">⚠️ Tab Zalo chưa nhận bot.</span>
        <button id="btn-fix-reload" style="background:#ef4444; color:#fff; border:none; border-radius:4px; padding:3px 8px; font-size:10px; font-weight:700; cursor:pointer;">
          🔄 Bấm F5 Zalo
        </button>
      `;
      const btnFix = document.getElementById('btn-fix-reload');
      if (btnFix) {
        btnFix.onclick = () => {
          chrome.tabs.reload(targetTab.id);
          btnFix.innerText = "⏳ Đang tải...";
          setTimeout(checkConnection, 2000);
        };
      }
    }
  }
  checkConnection();

  // ================== TAB 1 CONTROLLERS ==================
  btnParseActive.onclick = async () => {
    setStatus("Đang đọc tin nhắn và bóc tách đơn hàng...");
    const res = await sendToZaloTab({ action: "PARSE_ACTIVE_CHAT" });
    setStatus("", false);

    if (res && res.success && res.data) {
      const order = res.data;
      const exists = orders.some(o => o.phone && o.phone === order.phone);
      if (!exists) {
        orders.unshift({
          id: Date.now(),
          ...order,
          created_at: new Date().toLocaleTimeString('vi-VN')
        });
        saveOrders();
        renderOrders();
      }
    } else {
      alert(res?.error || "Không tìm thấy nội dung đơn hàng trong đoạn chat hiện tại.");
    }
  };

  btnAutoBatchScan.onclick = async () => {
    const tag = inputTargetTag.value.trim();
    if (!tag) {
      alert("Vui lòng nhập tên Thẻ Tag muốn quét (vd: Khách hàng)");
      return;
    }

    progressBox.classList.remove('hidden');
    progressBarFill.style.width = "0%";
    progressStatusText.innerText = `Đang bắt đầu quét thẻ "${tag}"...`;
    btnAutoBatchScan.disabled = true;

    const progressListener = (msg) => {
      if (msg.action === "BATCH_PROGRESS") {
        const percent = Math.round((msg.current / msg.total) * 100);
        progressBarFill.style.width = `${percent}%`;
        progressStatusText.innerText = `Đang duyệt ${msg.current}/${msg.total}: ${msg.name}`;
      }
    };
    chrome.runtime.onMessage.addListener(progressListener);

    const res = await sendToZaloTab({ action: "AUTO_BATCH_SCAN", targetTag: tag });
    
    chrome.runtime.onMessage.removeListener(progressListener);
    btnAutoBatchScan.disabled = false;
    progressBox.classList.add('hidden');

    if (res && res.success) {
      if (res.total === 0) {
        alert(`Không tìm thấy khách hàng nào trong thẻ "${tag}".\n👉 Gợi ý: Hãy bấm vào tab [${tag}] trên thanh phân loại của Zalo Web trước rồi bấm nút quét lại!`);
      } else {
        alert(`🎉 Hoàn tất quét tự động!\n- Tổng số khách: ${res.total}\n- Đã gom mới: ${res.savedCount} đơn hàng.`);
      }
    } else {
      alert(res?.error || "Không thể kết nối với tab Zalo Web. Hãy bấm nút 'Bấm F5 Zalo' trên thanh màu đỏ rồi thử lại!");
    }
  };

  btnStopBatch.onclick = async () => {
    await sendToZaloTab({ action: "STOP_BATCH_SCAN" });
    progressBox.classList.add('hidden');
    btnAutoBatchScan.disabled = false;
  };

  btnSyncToolPee.onclick = async () => {
    if (orders.length === 0) {
      alert("Chưa có đơn hàng nào để đẩy sang Tool Shopee!");
      return;
    }
    try {
      btnSyncToolPee.innerText = "⏳ Đang đẩy...";
      const resp = await fetch("http://localhost:8080/api/zalo/save-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orders: orders })
      });
      const data = await resp.json();
      if (data.success) {
        alert(`✅ Đã đồng bộ thành công ${orders.length} đơn hàng sang Tool Shopee (localhost:8080)!`);
      } else {
        alert("Lỗi từ server Tool Shopee: " + (data.error || "Không xác định"));
      }
    } catch (e) {
      alert("Không kết nối được với Tool Shopee trên máy (http://localhost:8080).\nHãy chắc chắn bạn đã chạy file CHAY_TOOL.bat!");
    } finally {
      btnSyncToolPee.innerText = "🔗 Đẩy Tool Shopee";
    }
  };

  function saveOrders() {
    chrome.storage.local.set({ saved_orders: orders });
  }

  function renderOrders() {
    orderCountEl.innerText = orders.length;
    if (orders.length === 0) {
      emptyState.style.display = 'block';
      orderListContainer.innerHTML = '';
      orderListContainer.appendChild(emptyState);
      return;
    }

    emptyState.style.display = 'none';
    orderListContainer.innerHTML = '';

    orders.forEach((o, index) => {
      const card = document.createElement('div');
      card.className = 'order-card';
      const linkDisplay = o.product_urls?.length 
        ? `<a href="${o.product_urls[0]}" target="_blank" style="color:#0068ff; text-decoration:none;">${o.product_urls[0].substring(0, 38)}...</a>`
        : '<span style="color:#94a3b8;">Không có</span>';

      card.innerHTML = `
        <div class="order-card-top">
          <span class="order-card-name">👤 ${o.customer_name || 'Khách Zalo'}</span>
          <span class="order-card-phone">${o.phone || 'Chưa có SĐT'}</span>
        </div>
        <div class="order-card-row">
          <span><strong>Link:</strong> ${linkDisplay}</span>
          ${o.voucher ? `<span><strong>Mã Voucher:</strong> <span class="order-card-voucher">${o.voucher}</span></span>` : ''}
          <span><strong>Địa chỉ mới:</strong> <span class="order-card-address-new">${o.address_new || 'Chưa rõ'}</span></span>
          ${o.address_old && o.address_old !== o.address_new ? `<span><strong>Địa chỉ cũ:</strong> <span class="order-card-address-old">${o.address_old}</span></span>` : ''}
        </div>
        <div class="order-card-actions">
          <button class="btn-text btn-copy-card" data-idx="${index}">📋 Copy</button>
          <button class="btn-text danger btn-delete-card" data-idx="${index}">🗑️ Xóa</button>
        </div>
      `;
      orderListContainer.appendChild(card);
    });

    document.querySelectorAll('.btn-copy-card').forEach(btn => {
      btn.onclick = (e) => {
        const idx = e.target.getAttribute('data-idx');
        const o = orders[idx];
        const copyText = `Tên: ${o.customer_name}\nSĐT: ${o.phone || ''}\nLink: ${o.product_urls?.join(', ')}\nMã: ${o.voucher || ''}\nĐịa chỉ mới: ${o.address_new || ''}\nĐịa chỉ cũ: ${o.address_old || ''}`;
        navigator.clipboard.writeText(copyText);
        alert("Đã copy đơn của: " + o.customer_name);
      };
    });

    document.querySelectorAll('.btn-delete-card').forEach(btn => {
      btn.onclick = (e) => {
        const idx = e.target.getAttribute('data-idx');
        orders.splice(idx, 1);
        saveOrders();
        renderOrders();
      };
    });
  }

  btnClearAll.onclick = () => {
    if (orders.length === 0) return;
    if (confirm("Bạn có chắc chắn muốn xóa tất cả danh sách đơn đã lọc không?")) {
      orders = [];
      saveOrders();
      renderOrders();
    }
  };

  btnExportCsv.onclick = () => {
    if (orders.length === 0) {
      alert("Không có đơn hàng nào để xuất!");
      return;
    }
    let csvContent = "\uFEFF";
    csvContent += "Tên Khách Hàng,Số Điện Thoại Thật,Link Sản Phẩm,Mã Giảm Giá,Địa Chỉ Mới (Sau sáp nhập),Địa Chỉ Cũ (Trước sáp nhập),Ghi Chú Sáp Nhập,Thời Gian\n";
    orders.forEach(o => {
      const row = [
        `"${(o.customer_name || '').replace(/"/g, '""')}"`,
        `"${(o.phone || '').replace(/"/g, '""')}"`,
        `"${(o.product_urls?.[0] || '').replace(/"/g, '""')}"`,
        `"${(o.voucher || '').replace(/"/g, '""')}"`,
        `"${(o.address_new || '').replace(/"/g, '""')}"`,
        `"${(o.address_old || '').replace(/"/g, '""')}"`,
        `"${(o.address_note || '').replace(/"/g, '""')}"`,
        `"${o.created_at || ''}"`
      ];
      csvContent += row.join(",") + "\n";
    });
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Don_Hang_Zalo_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ================== TAB 2: TRA MVĐ & BÁO KHÁCH ==================
  function updateSheetCountUI() {
    const withMvdCount = sheetOrders.filter(o => o.tracking_no || o.mvd).length;
    sheetOrderCountEl.innerText = `${sheetOrders.length} đơn (${withMvdCount} có MVĐ)`;
  }

  const inputSheetUrl = document.getElementById('input-sheet-url');

  async function syncSheetData(showAlert = true) {
    const rawUrl = (inputSheetUrl ? inputSheetUrl.value.trim() : "") || "https://shopee-tracker-pro-b1v8.onrender.com";
    const serverUrl = rawUrl.replace(/\/+$/, '');

    try {
      if (showAlert) btnSyncSheetOrders.innerText = "⏳ Đang tải...";
      
      let data = null;
      let usedUrl = serverUrl;

      // 1. Thử tải từ Render Cloud
      try {
        const resp = await fetch(`${serverUrl}/api/load-draft`, { cache: 'no-cache' });
        if (resp.ok) {
          data = await resp.json();
        }
      } catch (eCloud) {
        console.warn("[Zalo Bot] Thử Cloud thất bại, chuyển sang localhost...", eCloud);
      }

      // 2. Dự phòng thử localhost nếu Cloud lỗi hoặc chưa nạp được
      if (!data || !Array.isArray(data.rows)) {
        try {
          const respLocal = await fetch("http://localhost:8080/api/load-draft");
          if (respLocal.ok) {
            data = await respLocal.json();
            usedUrl = "http://localhost:8080";
          }
        } catch (eLocal) {}
      }

      if (data && Array.isArray(data.rows)) {
        sheetOrders = data.rows;
        chrome.storage.local.set({ 
          tracking_sheet_orders: sheetOrders,
          sheet_api_url: serverUrl 
        });
        updateSheetCountUI();
        if (showAlert) {
          alert(`🎉 ĐỒNG BỘ THÀNH CÔNG!\n- Đã nạp: ${sheetOrders.length} đơn hàng\n- Nguồn: ${usedUrl}`);
        }
      } else {
        if (showAlert) {
          alert(`Không tải được dữ liệu từ ${serverUrl} hoặc localhost:8080.\nHãy kiểm tra kết nối mạng hoặc thử lại sau vài giây (Render có thể đang khởi động)!`);
        }
      }
    } catch (e) {
      if (showAlert) {
        alert("Lỗi kết nối Sheet: " + e.message);
      }
    } finally {
      if (showAlert) btnSyncSheetOrders.innerHTML = `<span>🔄</span> Đồng Bộ Sheet Cloud`;
    }
  }

  btnSyncSheetOrders.onclick = () => syncSheetData(true);
  if (inputSheetUrl) {
    inputSheetUrl.onchange = () => {
      const u = inputSheetUrl.value.trim().replace(/\/+$/, '');
      chrome.storage.local.set({ sheet_api_url: u });
    };
  }

  // Tìm kiếm theo SĐT
  function searchMvdByPhone(phone) {
    if (!phone) {
      alert("Vui lòng nhập Số Điện Thoại cần tra cứu!");
      return;
    }
    if (sheetOrders.length === 0) {
      alert("Dữ liệu Sheet chưa có đơn hàng nào. Hãy bấm 'Đồng Bộ Sheet (8080)' trước!");
      return;
    }

    const matched = window.ZaloOrderParser.findOrderByPhone(phone, sheetOrders);
    if (matched) {
      currentFoundOrder = matched;
      renderMvdCard(matched);
    } else {
      currentFoundOrder = null;
      mvdResultCard.classList.add('hidden');
      mvdEmptyHint.classList.remove('hidden');
      alert(`Không tìm thấy đơn hàng nào khớp với SĐT: ${phone} trong Sheet!`);
    }
  }

  btnDoSearchPhone.onclick = () => {
    const phone = inputSearchPhone.value.trim();
    searchMvdByPhone(phone);
  };

  inputSearchPhone.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      searchMvdByPhone(inputSearchPhone.value.trim());
    }
  });

  // Tự động lấy SĐT từ chat Zalo đang mở
  btnGetPhoneFromChat.onclick = async () => {
    setStatus("Đang đọc tin nhắn lấy SĐT khách...");
    const res = await sendToZaloTab({ action: "PARSE_ACTIVE_CHAT" });
    setStatus("", false);

    if (res && res.success && res.data && res.data.phone) {
      inputSearchPhone.value = res.data.phone;
      searchMvdByPhone(res.data.phone);
    } else {
      alert("Không tìm thấy SĐT trong đoạn chat Zalo hiện tại. Hãy nhập SĐT bằng tay vào ô tìm kiếm!");
    }
  };

  function renderMvdCard(o) {
    mvdEmptyHint.classList.add('hidden');
    mvdResultCard.classList.remove('hidden');

    resCarrier.innerText = o.carrier || "Đơn vị vận chuyển";
    resMvd.innerText = o.tracking_no || "Chưa có MVĐ";
    resName.innerText = o.receiver_name || "Khách hàng";
    resPhone.innerText = o.receiver_phone || "";
    resStatus.innerText = o.status_desc || o.status_badge_text || "Đang xử lý";

    if (o.product_name) {
      rowProd.style.display = 'block';
      resProduct.innerText = o.product_name.length > 50 ? o.product_name.substring(0, 48) + "..." : o.product_name;
    } else {
      rowProd.style.display = 'none';
    }

    const cod = o.cod_amount || (o.cod_val ? `${Number(o.cod_val).toLocaleString('vi-VN')} đ` : "");
    if (cod && cod !== "0 đ") {
      rowCod.style.display = 'block';
      resCod.innerText = cod;
    } else {
      rowCod.style.display = 'none';
    }

    if (o.driver_phone) {
      rowDriver.style.display = 'block';
      resDriver.innerText = o.driver_phone;
    } else {
      rowDriver.style.display = 'none';
    }
  }

  // Điền vào Chat Zalo
  btnInsertZalo.onclick = async () => {
    if (!currentFoundOrder) return;
    const msg = window.ZaloOrderParser.buildTrackingReplyMessage(currentFoundOrder);
    btnInsertZalo.innerText = "⏳ Đang điền...";
    const res = await sendToZaloTab({ action: "INSERT_CHAT_MESSAGE", text: msg });
    btnInsertZalo.innerHTML = `<span>💬</span> Điền Vào Chat Zalo`;

    if (res && res.success) {
      alert("✅ Đã điền tin nhắn báo Mã Vận Đơn vào ô chat Zalo!\n👉 Bạn chỉ cần nhấn phím Enter để gửi cho khách.");
    } else {
      // Fallback copy
      navigator.clipboard.writeText(msg);
      alert("📋 Đã copy tin nhắn báo MVĐ vào bộ nhớ tạm!\n👉 Hãy nhấn Ctrl + V vào ô chat Zalo để dán và gửi cho khách.");
    }
  };

  // Copy tin nhắn
  btnCopyReply.onclick = () => {
    if (!currentFoundOrder) return;
    const msg = window.ZaloOrderParser.buildTrackingReplyMessage(currentFoundOrder);
    navigator.clipboard.writeText(msg);
    alert("📋 Đã sao chép nội dung tin nhắn báo mã vận đơn!");
  };
});
