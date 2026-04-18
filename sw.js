// ツキヨガ Service Worker
// PWA判定を通すための最小実装。将来オフライン対応を追加する時はここに書く。

const CACHE_VERSION = 'tsukiyoga-v1';

self.addEventListener('install', (event) => {
  // すぐに有効化
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // 古いキャッシュを消す
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // デフォルト動作（ネットワーク通常アクセス）
  // オフライン対応は将来追加する
});
