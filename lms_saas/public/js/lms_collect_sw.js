/* Minimal service worker for field collection offline shell */
self.addEventListener("install", function (event) {
	self.skipWaiting();
});

self.addEventListener("fetch", function (event) {
	event.respondWith(fetch(event.request).catch(function () {
		return caches.match(event.request);
	}));
});
