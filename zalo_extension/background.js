/**
 * Service Worker cho Zalo Order Filter Extension
 */

chrome.runtime.onInstalled.addListener(() => {
  console.log("[Zalo Order Filter Bot] Extension installed.");
  // Khởi tạo storage mặc định
  chrome.storage.local.get(['gemini_api_key', 'saved_orders'], (res) => {
    if (!res.saved_orders) {
      chrome.storage.local.set({ saved_orders: [] });
    }
  });
});
