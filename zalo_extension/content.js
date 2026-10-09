/**
 * Content Script chạy trực tiếp trên chat.zalo.me
 * Zalo Order Filter Bot v2.1
 * Tự động tìm kiếm hội thoại, tự động quét theo tag và tự động bóc tách tin nhắn
 */

(() => {
  console.log("[Zalo Order Filter Bot] Content script v2.1 đã sẵn sàng trên chat.zalo.me");

  let geminiApiKey = "";
  let autoCaptureEnabled = true;
  let isScanningBatch = false;
  let lastProcessedFingerprint = "";

  // 1. Tải cấu hình từ Storage
  if (chrome?.storage?.local) {
    chrome.storage.local.get(['gemini_api_key', 'auto_capture_enabled'], (res) => {
      if (res.gemini_api_key) geminiApiKey = res.gemini_api_key;
      if (res.auto_capture_enabled !== undefined) autoCaptureEnabled = res.auto_capture_enabled;
      updateFloatingButtonBadge();
    });

    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === 'local') {
        if (changes.gemini_api_key) geminiApiKey = changes.gemini_api_key.newValue || "";
        if (changes.auto_capture_enabled !== undefined) {
          autoCaptureEnabled = !!changes.auto_capture_enabled.newValue;
          updateFloatingButtonBadge();
        }
      }
    });
  }

  /**
   * Hiển thị Toast thông báo đẹp mắt trên màn hình Zalo
   */
  function showToast(title, msg, type = 'success', duration = 3500) {
    let container = document.getElementById('zalo-bot-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'zalo-bot-toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `zalo-bot-toast ${type}`;
    
    let icon = "⚡";
    if (type === "info") icon = "ℹ️";
    if (type === "warning") icon = "⚠️";
    if (type === "error") icon = "❌";

    toast.innerHTML = `
      <span class="zalo-bot-toast-icon">${icon}</span>
      <div class="zalo-bot-toast-content">
        <div class="zalo-bot-toast-title">${title}</div>
        <div class="zalo-bot-toast-msg">${msg}</div>
      </div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(40px)';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  /**
   * 2. Lấy thông tin cuộc trò chuyện hiện tại đang mở trên màn hình
   */
  function getCurrentChatInfo() {
    let chatName = "";
    const headerTitleEl = document.querySelector(
      '.header-title, [data-id="chat-header-name"], .conv-header__name, .thread-chat__title, .user-name, .header-chat__title, .fl-chat-title, .chat-title'
    );
    if (headerTitleEl) {
      chatName = headerTitleEl.innerText.trim();
    }

    // Thu thập thẻ phân loại (Tag) của cuộc trò chuyện hiện tại
    let currentChatTags = [];
    
    // 1. Tìm trên thanh header trò chuyện (như nhãn 🔴 Khách hàng dưới tên người chat)
    const headerContainer = headerTitleEl ? headerTitleEl.closest('.chat-header, .header, .conv-header, [data-id="chat-header"], .chat-box__header, div[class*="header"]') : null;
    if (headerContainer) {
      const tagEls = headerContainer.querySelectorAll('[class*="tag"], [class*="label"], [class*="classify"], [class*="badge"], .fl-tag, [data-id*="tag"]');
      tagEls.forEach(t => {
        const txt = (t.innerText || t.getAttribute('title') || '').trim();
        if (txt && !txt.toLowerCase().includes(chatName.toLowerCase())) {
          currentChatTags.push(txt.toLowerCase());
        }
      });
    }

    // 2. Tìm trên item đang active ở danh sách bên trái
    const activeSidebarItem = document.querySelector(
      '.conv-item.active, [data-id^="conv-"].active, [class*="conv-item"][class*="active"], [class*="selected"], div[id^="conv-rel-"].active'
    );
    if (activeSidebarItem) {
      const sidebarTagEls = activeSidebarItem.querySelectorAll('[class*="tag"], [class*="label"], [class*="classify"], [class*="badge"], .fl-tag, [data-id*="tag"], span[title], div[title]');
      sidebarTagEls.forEach(t => {
        const txt = (t.getAttribute('title') || t.innerText || t.getAttribute('aria-label') || '').trim();
        if (txt && txt.length <= 30) currentChatTags.push(txt.toLowerCase());
      });
      // Dự phòng quét text toàn bộ item
      const fullItemText = (activeSidebarItem.innerText || "").toLowerCase();
      currentChatTags.push(fullItemText);
    }

    // 3. Kiểm tra xem Zalo Web có đang bật filter theo tag ở thanh trên cùng không
    const activeFilterPills = document.querySelectorAll(
      '[class*="filter-tag"], [class*="filter-item"], [class*="chip"], [class*="tag-filter"], [class*="tab-item"]'
    );
    activeFilterPills.forEach(pill => {
      const isSelected = pill.classList.contains('active') || pill.classList.contains('selected') || pill.innerText.includes('×') || pill.innerText.includes('x');
      if (isSelected) {
        const txt = pill.innerText?.replace(/[×x]/g, '')?.trim();
        if (txt) currentChatTags.push(txt.toLowerCase());
      }
    });

    // Kiểm tra xem có phải nhóm chat không
    const isGroup = !!document.querySelector('.group-chat, [data-id="chat-header-group"], [class*="group-avatar"], .fl-group');

    // Tìm tất cả các tin nhắn hiển thị trong khung chat
    const messageElements = document.querySelectorAll(
      '.message-view, .chat-message, [data-id="div_ReceivedMsg_Text"], .msg-item, .bubble-message, .card, [data-id*="msg"], .text-msg, .chat-msg-text'
    );

    let messages = [];
    messageElements.forEach(el => {
      const text = el.innerText?.trim();
      if (text && text.length >= 3) {
        const isMe = el.closest('.chat-message--right, .is-me, .me, [data-id="div_SentMsg_Text"], .msg-sent');
        messages.push({
          text: text,
          isCustomer: !isMe
        });
      }
    });

    return {
      sender_name: chatName || "Khách Zalo",
      tags: [...new Set(currentChatTags)],
      is_group: isGroup,
      messages: messages
    };
  }

  /**
   * 3. Bóc tách đơn hàng từ cuộc hội thoại hiện tại
   */
  async function parseCurrentActiveChat() {
    const chatInfo = getCurrentChatInfo();
    const customerMessages = chatInfo.messages.filter(m => m.isCustomer).map(m => m.text);
    
    // Thu thập tin nhắn gần nhất
    const candidateTexts = customerMessages.length > 0 
      ? customerMessages.slice(-8).join("\n---\n") 
      : chatInfo.messages.slice(-8).map(m => m.text).join("\n---\n");

    if (!candidateTexts || candidateTexts.length < 5) {
      return null;
    }

    if (!window.ZaloOrderParser) {
      console.warn("[Zalo Bot] ZaloOrderParser chưa sẵn sàng!");
      return null;
    }

    const parsed = await window.ZaloOrderParser.parseOrderMessage(
      candidateTexts,
      chatInfo.sender_name,
      geminiApiKey
    );

    return parsed;
  }

  /**
   * 4. Lưu đơn hàng vào Storage và đồng bộ sang Tool Shopee nếu có
   */
  async function saveOrderToStorage(order) {
    if (!order) return false;
    
    const hasPhone = !!order.phone;
    const hasLink = order.product_urls && order.product_urls.length > 0;
    const hasAddress = !!order.address_new;

    if (!hasPhone && !hasLink && !hasAddress) {
      return false;
    }

    return new Promise((resolve) => {
      chrome.storage.local.get(['saved_orders'], async (res) => {
        let orders = res.saved_orders || [];
        
        // Tránh trùng lặp
        const isDuplicate = orders.some(existing => {
          if (order.phone && existing.phone && order.phone === existing.phone) return true;
          if (order.customer_name === existing.customer_name && 
              order.product_urls?.[0] === existing.product_urls?.[0] &&
              order.address_new === existing.address_new) {
            return true;
          }
          return false;
        });

        if (!isDuplicate) {
          const newOrder = {
            id: Date.now(),
            ...order,
            created_at: new Date().toLocaleTimeString('vi-VN')
          };
          orders.unshift(newOrder);

          chrome.storage.local.set({ saved_orders: orders }, () => {
            console.log("[Zalo Bot] Đã tự động lưu đơn mới:", newOrder);
            showToast(
              `⚡ Tự Động Bắt Đơn: ${order.customer_name}`,
              `SĐT: ${order.phone || 'Chưa có'} | Đ/c: ${order.address_new || 'Chưa có'}`
            );

            // Đồng bộ sang Server Tool Shopee (localhost:8080)
            syncOrderToToolPee(orders);
            resolve(true);
          });
        } else {
          resolve(false);
        }
      });
    });
  }

  async function syncOrderToToolPee(orders) {
    try {
      await fetch("http://localhost:8080/api/zalo/save-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orders: orders })
      });
    } catch (e) {}
  }

  /**
   * 5. VÒNG LẶP THEO DÕI TỰ ĐỘNG KHI MỞ CHAT HOẶC CÓ TIN MỚI
   */
  let autoCheckTimer = null;
  function triggerAutoCheck() {
    if (!autoCaptureEnabled || isScanningBatch) return;

    clearTimeout(autoCheckTimer);
    autoCheckTimer = setTimeout(async () => {
      const chatInfo = getCurrentChatInfo();
      if (!chatInfo.sender_name || chatInfo.messages.length === 0) return;

      const currentMsgSnippet = chatInfo.messages.slice(-3).map(m => m.text).join("|");
      const currentFingerprint = `${chatInfo.sender_name}_${currentMsgSnippet}`;

      if (currentFingerprint === lastProcessedFingerprint) {
        return;
      }

      const combined = currentMsgSnippet.toLowerCase();
      const hasOrderCues = /(0\d{8,9}|không|sđt|sdt|đc|địa\s*chỉ|cổng\s*làng|xã|thôn|phường|quận|huyện|shopee|shp\.ee|s\.shopee|tiktok|gửi\s*về|ship\s*về|áp\s*mã|voucher|1️⃣|2️⃣)/i.test(combined);

      if (hasOrderCues) {
        lastProcessedFingerprint = currentFingerprint;
        const parsed = await parseCurrentActiveChat();
        if (parsed) {
          await saveOrderToStorage(parsed);
        }
      }

      // Kích hoạt Chatbot tự động phản hồi mã vận đơn khi khách nhắn SĐT
      await checkCustomerPhoneAndAutoReply();
    }, 800);
  }

  const observer = new MutationObserver(() => {
    triggerAutoCheck();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });

  /**
   * 6. TÌM TẤT CẢ CÁC HỘI THOẠI BÊN CỘT TRÁI
   */
  function getAllSidebarConversationItems() {
    // Thu thập các selector phổ biến của Zalo Web
    let items = Array.from(document.querySelectorAll(
      'div[id^="conv-rel-"], .conv-item, [data-id^="conv-item-"], [data-id^="conv_"], .thread-item, .chat-item, div[class*="conv-item"], div[class*="thread-item"], [data-id="thread-item"]'
    ));

    // Dự phòng tìm kiếm trong container
    if (items.length === 0) {
      const listContainer = document.querySelector(
        '#chat-message-list, [data-id="message-list"], .conv-list, .message-list, div[class*="message-list"], div[class*="conv-list"], .virtual-list'
      );
      if (listContainer) {
        const children = Array.from(listContainer.querySelectorAll(':scope > div, :scope > div > div, .virtual-list > div'));
        items = children.filter(c => {
          const hasTitle = c.querySelector('.conv-item-title, .name, [class*="title"], [class*="name"]');
          const hasImg = c.querySelector('img, [class*="avatar"]');
          return (hasTitle || hasImg) && c.offsetHeight > 25;
        });
      }
    }

    // Lọc trùng phần tử lồng nhau
    const cleanList = [];
    items.forEach(it => {
      if (!cleanList.some(c => c === it || c.contains(it))) {
        cleanList.push(it);
      }
    });

    return cleanList;
  }

  /**
   * 7. TÌM HỘI THOẠI KHỚP THẺ TAG (Hỗ trợ nhiều tag phân cách bằng dấu phẩy)
   */
  function findConversationsByTag(targetTag = "") {
    const rawTag = (targetTag || "").trim().toLowerCase();
    const tagList = rawTag ? rawTag.split(/[,;|]/).map(t => t.trim().toLowerCase()).filter(Boolean) : [];
    
    // 1. Kiểm tra xem người dùng có đang bấm chọn bộ lọc thẻ Tag ở trên cùng danh sách Zalo Web không
    const filterPills = document.querySelectorAll(
      '[class*="filter"], [class*="chip"], [class*="tag"], .tab-item, div[class*="tag-filter"], .filter-item, [data-id*="filter"]'
    );
    let isZaloFilterActive = false;
    filterPills.forEach(pill => {
      const pillText = (pill.innerText || "").toLowerCase();
      const matchesAnyPill = tagList.length === 0 || tagList.some(t => pillText.includes(t));
      if (matchesAnyPill) {
        const hasCloseBtn = pill.querySelector('.icon-close, [class*="close"], [class*="delete"], i, svg');
        const isActiveClass = pill.classList.contains('active') || pill.classList.contains('selected');
        if (hasCloseBtn || isActiveClass || pillText.includes('×') || pillText.includes('x')) {
          isZaloFilterActive = true;
        }
      }
    });

    const allItems = getAllSidebarConversationItems();
    console.log(`[Zalo Bot] Tổng số hội thoại tìm thấy: ${allItems.length}. Tag list:`, tagList);

    const matched = [];

    allItems.forEach(item => {
      // Lấy tên người chat
      let name = "";
      const nameEl = item.querySelector('.conv-item-title, .name, .title, [class*="title"], [class*="name"], span[title], div[title]');
      if (nameEl) {
        name = nameEl.getAttribute('title') || nameEl.innerText?.trim() || "";
      }
      if (!name) {
        name = item.innerText?.split('\n')[0]?.trim() || "Khách Zalo";
      }

      let isMatch = false;

      // Nếu đang bật sẵn bộ lọc trên Zalo Web -> TẤT CẢ các item trong danh sách đều thuộc tag đó!
      if (isZaloFilterActive) {
        isMatch = true;
      } else if (tagList.length > 0) {
        const itemText = (item.innerText || "").toLowerCase();
        if (tagList.some(t => itemText.includes(t))) {
          isMatch = true;
        } else {
          // Tìm trong tooltip, title hoặc class tag
          const taggedEls = item.querySelectorAll('[title], [aria-label], [data-tooltip], [class*="tag"], [class*="label"], [class*="classify"], [class*="badge"]');
          for (const el of taggedEls) {
            const attr = ((el.getAttribute('title') || '') + " " + (el.getAttribute('aria-label') || '') + " " + (el.innerText || '')).toLowerCase();
            if (tagList.some(t => attr.includes(t))) {
              isMatch = true;
              break;
            }
          }
        }
      }

      // Nếu người dùng yêu cầu lọc tất cả
      if (tagList.length === 0 || rawTag === "all" || rawTag === "tất cả") {
        isMatch = true;
      }

      if (isMatch) {
        matched.push({
          element: item,
          title: name
        });
      }
    });

    return matched;
  }

  /**
   * Kích hoạt click vào một phần tử trên Zalo Web
   */
  function triggerClick(el) {
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    const target = el.querySelector('.conv-item-title, .name, [class*="title"], img, .avatar') || el;
    const opts = { bubbles: true, cancelable: true, view: window };
    ['mousedown', 'mouseup', 'click'].forEach(evt => {
      target.dispatchEvent(new MouseEvent(evt, opts));
    });
  }

  /**
   * 8. TỰ ĐỘNG QUÉT HÀNG LOẠT KHÁCH CÓ GẮN TAG (Auto Batch Crawl)
   */
  async function runAutoBatchScan(targetTag = "Khách hàng", onProgress = null) {
    if (isScanningBatch) {
      alert("Đang có tiến trình quét tự động chạy, vui lòng chờ!");
      return { total: 0, savedCount: 0 };
    }

    isScanningBatch = true;
    const items = findConversationsByTag(targetTag);
    const total = items.length;

    if (total === 0) {
      isScanningBatch = false;
      showToast("Quét Tự Động", `Không tìm thấy khách hàng nào trong thẻ "${targetTag}"`, "warning");
      return { total: 0, savedCount: 0 };
    }

    showToast("Bắt Đầu Quét", `Đang tự động duyệt ${total} khách hàng có thẻ "${targetTag}"...`, "info");
    let savedCount = 0;

    for (let i = 0; i < total; i++) {
      if (!isScanningBatch) break;
      const item = items[i];
      
      if (onProgress) {
        onProgress(i + 1, total, item.title);
      }

      // Click mở đoạn chat
      triggerClick(item.element);

      // Đợi tin nhắn tải ra màn hình (1.3 giây)
      await new Promise(r => setTimeout(r, 1300));

      // Bóc tách đơn
      try {
        const order = await parseCurrentActiveChat();
        if (order) {
          const isSaved = await saveOrderToStorage(order);
          if (isSaved) savedCount++;
        }
      } catch (err) {
        console.error("[Zalo Bot] Lỗi bóc tách hội thoại:", item.title, err);
      }
    }

    isScanningBatch = false;
    showToast(
      "🎉 Quét Hoàn Tất!",
      `Đã duyệt ${total} khách hàng. Thu thập thành công ${savedCount} đơn mới!`,
      "success",
      5000
    );

    return { total: total, savedCount: savedCount };
  }

  /**
   * 9. CHÈN TIN NHẮN VÀO Ô CHAT ZALO WEB
   */
  function insertTextToZaloInput(text) {
    if (!text) return false;
    const inputEl = document.querySelector(
      '#input_quill, div[contenteditable="true"], [data-id="chat-input"], .chat-input, [data-id="rich-input"]'
    );
    if (inputEl) {
      inputEl.focus();
      try {
        // Dùng execCommand để Quill Editor trên Zalo Web nhận diện thay đổi
        document.execCommand('insertText', false, text);
        return true;
      } catch (e) {
        inputEl.innerText = text;
        return true;
      }
    }
    // Fallback: sao chép vào bộ nhớ tạm
    navigator.clipboard.writeText(text);
    return false;
  }

  /**
   * Kích hoạt nút Gửi tin nhắn trên Zalo Web
   */
  function triggerSendZaloMessage() {
    setTimeout(() => {
      const sendBtn = document.querySelector(
        '[data-id="btn-send"], [data-id="btn_SendMsg"], .btn-send, [title*="Gửi"], [aria-label*="Gửi"], div[class*="send"]'
      );
      if (sendBtn) {
        sendBtn.click();
      } else {
        const inputEl = document.querySelector('#input_quill, div[contenteditable="true"]');
        if (inputEl) {
          inputEl.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
          inputEl.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
          inputEl.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
        }
      }
    }, 350);
  }

  /**
   * Lấy danh sách đơn hàng trong Sheet (Ưu tiên Render Cloud https://shopee-tracker-pro-b1v8.onrender.com)
   */
  async function getSheetOrders() {
    return new Promise((resolve) => {
      chrome.storage.local.get(['tracking_sheet_orders', 'sheet_api_url'], async (res) => {
        let list = res.tracking_sheet_orders || [];
        const rawUrl = (res.sheet_api_url || "https://shopee-tracker-pro-b1v8.onrender.com").replace(/\/+$/, '');

        if (list.length === 0) {
          // 1. Thử tải trực tiếp từ Render Cloud
          try {
            const resp = await fetch(`${rawUrl}/api/load-draft`, { cache: 'no-cache' });
            if (resp.ok) {
              const data = await resp.json();
              if (data && Array.isArray(data.rows) && data.rows.length > 0) {
                list = data.rows;
                chrome.storage.local.set({ tracking_sheet_orders: list });
                console.log(`[Zalo Bot] Đã nạp ${list.length} đơn hàng từ Cloud: ${rawUrl}`);
              }
            }
          } catch (eCloud) {
            console.warn("[Zalo Bot] Không kết nối được Render Cloud, thử localhost:8080...", eCloud);
          }

          // 2. Dự phòng thử localhost nếu Cloud chưa được
          if (list.length === 0) {
            try {
              const respLocal = await fetch("http://localhost:8080/api/load-draft");
              if (respLocal.ok) {
                const data = await respLocal.json();
                if (data && Array.isArray(data.rows) && data.rows.length > 0) {
                  list = data.rows;
                  chrome.storage.local.set({ tracking_sheet_orders: list });
                }
              }
            } catch (eLocal) {}
          }
        }
        resolve(list);
      });
    });
  }

  /**
   * Tra cứu đơn hàng theo SĐT và tự động tạo tin nhắn báo mã vận đơn
   */
  async function lookupAndReplyMVD(targetPhone = null, autoSend = false) {
    let phone = targetPhone;
    if (!phone) {
      const chatInfo = getCurrentChatInfo();
      const allText = chatInfo.messages.map(m => m.text).join("\n");
      phone = window.ZaloOrderParser.cleanPhoneNumber(allText);
    }

    if (!phone) {
      showToast("Tra Cứu MVĐ", "Không tìm thấy SĐT nào trong đoạn chat của khách này!", "warning");
      return null;
    }

    let matchedOrders = [];

    // 1. Tra cứu trực tiếp từ dữ liệu Sheet (Render Cloud / Localhost)
    const sheetOrders = await getSheetOrders();
    if (sheetOrders.length > 0 && window.ZaloOrderParser.findAllOrdersByPhone) {
      matchedOrders = window.ZaloOrderParser.findAllOrdersByPhone(phone, sheetOrders);
    }

    // 2. Dự phòng gọi API localhost nếu chưa tìm thấy
    if (matchedOrders.length === 0) {
      try {
        const encodedPhone = encodeURIComponent(phone);
        const resp = await fetch(`http://localhost:8080/api/zalo/lookup-mvd?phone=${encodedPhone}`);
        const data = await resp.json();
        if (data && data.success && Array.isArray(data.orders)) {
          matchedOrders = data.orders;
        }
      } catch (e) {}
    }

    if (matchedOrders.length === 0) {
      const notFoundMsg = `Dạ chào bạn, shop đã kiểm tra hệ thống theo SĐT ${phone} nhưng hiện tại chưa thấy đơn hàng nào có mã vận đơn. Bạn vui lòng kiểm tra lại SĐT hoặc gửi tin nhắn để shop kiểm tra hỗ trợ bạn nhé! ❤️`;
      const ok = insertTextToZaloInput(notFoundMsg);
      if (autoSend && ok) {
        triggerSendZaloMessage();
      }
      showToast("Không Thấy Đơn", `Đã báo khách SĐT ${phone} chưa có mã vận đơn!`, "warning");
      return null;
    }

    // Tạo tin nhắn trả lời (hỗ trợ cả trường hợp 1 khách có nhiều đơn)
    const replyMsg = window.ZaloOrderParser.buildMultiOrderTrackingMessage 
      ? window.ZaloOrderParser.buildMultiOrderTrackingMessage(phone, matchedOrders)
      : window.ZaloOrderParser.buildTrackingReplyMessage(matchedOrders[0]);

    const ok = insertTextToZaloInput(replyMsg);

    if (autoSend && ok) {
      triggerSendZaloMessage();
      showToast(
        `🤖 [Bot Zalo] Đã Tự Động Trả Lời Khách!`,
        `Đã gửi ${matchedOrders.length} mã vận đơn cho SĐT ${phone}!`,
        "success",
        5000
      );
    } else {
      showToast(
        `📦 Tìm thấy ${matchedOrders.length} đơn có MVĐ cho SĐT: ${phone}`,
        ok ? "Đã điền tin nhắn vào ô chat! Bấm Enter để gửi." : "Đã copy tin nhắn báo MVĐ vào clipboard!",
        "success",
        5000
      );
    }

    return matchedOrders;
  }

  // Quản lý các tin nhắn đã trả lời tự động để tránh lặp
  const repliedChatMap = new Set();

  /**
   * Bộ giám sát Chatbot: Khi khách hàng nhắn tin -> Tự động nhận diện và phản hồi ngay 24/7!
   * TÍCH HỢP BẢO VỆ NICK CHÍNH: Chỉ phản hồi những ai có gắn Thẻ Tag (như "Khách hàng"),
   * tuyệt đối KHÔNG can thiệp vào tin nhắn của bạn bè, gia đình, người thân hay nhóm chat!
   */
  async function checkCustomerPhoneAndAutoReply() {
    chrome.storage.local.get([
      'auto_reply_mvd_bot', 'auto_send_directly', 
      'only_reply_tagged_customers', 'target_tag'
    ], async (res) => {
      const isBotEnabled = res.auto_reply_mvd_bot !== undefined ? !!res.auto_reply_mvd_bot : true;
      const autoSend = res.auto_send_directly !== undefined ? !!res.auto_send_directly : true;
      const onlyTagged = res.only_reply_tagged_customers !== undefined ? !!res.only_reply_tagged_customers : true; // MẶC ĐỊNH BẬT
      const rawTag = (res.target_tag || "Khách hàng").trim().toLowerCase();
      const tagList = rawTag ? rawTag.split(/[,;|]/).map(t => t.trim().toLowerCase()).filter(Boolean) : ["khách hàng"];

      if (!isBotEnabled) return;

      const chatInfo = getCurrentChatInfo();
      if (!chatInfo.messages || chatInfo.messages.length === 0) return;

      // 1. TUYỆT ĐỐI BỎ QUA NHÓM CHAT (Không can thiệp vào group)
      if (chatInfo.is_group) return;

      // 2. BẢO VỆ NICK CHÍNH: Nếu bật "Chỉ bot với người có Thẻ Tag", kiểm tra xem người này có tag không
      if (onlyTagged) {
        const hasTag = (chatInfo.tags || []).some(chatTag => {
          return tagList.some(target => chatTag.includes(target));
        });
        if (!hasTag) {
          // Người này KHÔNG có bất kỳ thẻ tag nào trong danh sách (Là bạn bè, người thân, đối tác...)
          // BOT BỎ QUA 100%, để bạn tự chat bằng tay bình thường!
          return;
        }
      }

      // Lấy tin nhắn mới nhất
      const lastMsg = chatInfo.messages[chatInfo.messages.length - 1];
      if (!lastMsg || !lastMsg.isCustomer) return; // Chỉ phản hồi tin nhắn của KHÁCH

      const msgText = (lastMsg.text || "").trim();
      const replyKey = `${chatInfo.sender_name}_${msgText}`;
      if (repliedChatMap.has(replyKey)) return;

      const phoneInMsg = window.ZaloOrderParser.cleanPhoneNumber(msgText);

      // TRƯỜNG HỢP 1: Khách gửi Số Điện Thoại
      if (phoneInMsg) {
        repliedChatMap.add(replyKey);
        console.log(`[Zalo Bot Auto-Reply] Phát hiện khách gửi SĐT: ${phoneInMsg}. Bắt đầu tra cứu và phản hồi...`);
        await lookupAndReplyMVD(phoneInMsg, autoSend);
        return;
      }

      // TRƯỜNG HỢP 2: Khách chào hỏi hoặc hỏi mã vận đơn (nhưng chưa gửi SĐT)
      const isGreetingOrAsking = /^(alo|shop|shop ơi|hi|hello|xin chào|chào shop|check đơn|tra đơn|cho mình xin mã|cho em xin mã|mã vận đơn|mvd|vận đơn|giao chưa|đơn đâu)/i.test(msgText);
      if (isGreetingOrAsking && msgText.length < 50) {
        repliedChatMap.add(replyKey);
        const guideMsg = `Dạ chào bạn! Đây là Bot Tra Cứu Đơn Hàng Tự Động của shop 🤖\n👉 Bạn vui lòng nhắn Số Điện Thoại nhận hàng để shop gửi mã vận đơn và tình trạng giao hàng cho bạn ngay nhé! ❤️`;
        const ok = insertTextToZaloInput(guideMsg);
        if (autoSend && ok) {
          triggerSendZaloMessage();
          showToast("🤖 Bot Zalo", "Đã tự động gửi lời chào & hướng dẫn khách gửi SĐT!", "info");
        }
      }
    });
  }

  /**
   * 10. Nút nổi Widget góc phải màn hình
   */
  function updateFloatingButtonBadge() {
    const btn = document.getElementById('zalo-bot-float-btn');
    if (btn) {
      btn.innerHTML = autoCaptureEnabled 
        ? `<span>⚡</span> Tự Động Bắt Đơn (BẬT)`
        : `<span>⏸️</span> Lọc Đơn Khách`;
    }
  }

  function injectFloatingWidget() {
    if (document.getElementById('zalo-bot-float-container')) return;

    const container = document.createElement('div');
    container.id = 'zalo-bot-float-container';
    container.innerHTML = `
      <button id="zalo-bot-float-btn" title="Bấm để lọc đơn hội thoại đang mở">
        <span>⚡</span> Tự Động Bắt Đơn (BẬT)
      </button>
      <button id="zalo-bot-mvd-btn" title="Tra cứu mã vận đơn theo SĐT trong Sheet và điền tin nhắn báo khách">
        <span>📦</span> Tra MVĐ Báo Khách
      </button>
    `;
    document.body.appendChild(container);

    document.getElementById('zalo-bot-float-btn').onclick = async () => {
      const btn = document.getElementById('zalo-bot-float-btn');
      btn.innerText = "⏳ Đang lọc...";
      try {
        const order = await parseCurrentActiveChat();
        if (order) {
          await saveOrderToStorage(order);
          showToast(`⚡ Đã Lọc: ${order.customer_name}`, `SĐT: ${order.phone || 'Chưa có'} | Đ/c: ${order.address_new || 'Chưa có'}`);
        } else {
          showToast("Zalo Bot", "Không tìm thấy nội dung đơn hàng trong đoạn chat này.", "warning");
        }
      } catch (e) {
        console.error(e);
        showToast("Lỗi", e.message, "error");
      } finally {
        updateFloatingButtonBadge();
      }
    };

    document.getElementById('zalo-bot-mvd-btn').onclick = async () => {
      const btn = document.getElementById('zalo-bot-mvd-btn');
      btn.innerText = "⏳ Đang tra...";
      try {
        await lookupAndReplyMVD();
      } catch (e) {
        showToast("Lỗi Tra Cứu", e.message, "error");
      } finally {
        btn.innerHTML = `<span>📦</span> Tra MVĐ Báo Khách`;
      }
    };
  }

  setTimeout(() => {
    injectFloatingWidget();
  }, 1000);

  /**
   * 11. Lắng nghe yêu cầu từ Popup Extension
   */
  if (chrome?.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === "PING") {
        const chatInfo = getCurrentChatInfo();
        sendResponse({
          success: true,
          connected: true,
          currentChat: chatInfo.sender_name,
          autoCapture: autoCaptureEnabled
        });
        return true;
      }

      if (request.action === "PARSE_ACTIVE_CHAT") {
        parseCurrentActiveChat().then(async (order) => {
          if (order) {
            await saveOrderToStorage(order);
          }
          sendResponse({ success: true, data: order });
        }).catch(err => {
          sendResponse({ success: false, error: err.message });
        });
        return true;
      }

      if (request.action === "AUTO_BATCH_SCAN") {
        runAutoBatchScan(request.targetTag, (current, total, name) => {
          chrome.runtime.sendMessage({
            action: "BATCH_PROGRESS",
            current: current,
            total: total,
            name: name
          }).catch(() => {});
        }).then(res => {
          sendResponse({ success: true, ...res });
        }).catch(err => {
          sendResponse({ success: false, error: err.message });
        });
        return true;
      }

      if (request.action === "STOP_BATCH_SCAN") {
        isScanningBatch = false;
        sendResponse({ success: true });
        return true;
      }

      if (request.action === "SET_AUTO_CAPTURE") {
        autoCaptureEnabled = !!request.enabled;
        chrome.storage.local.set({ auto_capture_enabled: autoCaptureEnabled });
        updateFloatingButtonBadge();
        sendResponse({ success: true, autoCapture: autoCaptureEnabled });
        return true;
      }

      if (request.action === "INSERT_CHAT_MESSAGE") {
        const ok = insertTextToZaloInput(request.text);
        sendResponse({ success: ok });
        return true;
      }

      if (request.action === "LOOKUP_MVD_CURRENT_CHAT") {
        lookupAndReplyMVD(request.phone).then(order => {
          sendResponse({ success: true, order: order });
        }).catch(err => {
          sendResponse({ success: false, error: err.message });
        });
        return true;
      }
    });
  }
})();

