// Service worker del sistema (PWA).
// Estrategia: los archivos estáticos se sirven desde la caché y se actualizan
// en segundo plano (stale-while-revalidate); las páginas
// siempre van a la red y, si no hay conexión, se muestra la página "offline".
const CACHE = "sistgestion-v2";
const PRECACHE = [{% for url in precache %}"{{ url|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];
const OFFLINE_URL = "{% url 'core:offline' %}";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Páginas: red primero, página offline si falla
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  // Estáticos: responde con la caché y la actualiza en segundo plano
  if (url.pathname.startsWith("{{ static_prefix }}")) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(req).then((cached) => {
          const red = fetch(req)
            .then((res) => {
              if (res.ok) cache.put(req, res.clone());
              return res;
            })
            .catch(() => cached);
          return cached || red;
        })
      )
    );
  }
});
