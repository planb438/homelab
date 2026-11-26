export default {
  async fetch(request, env) {
    const u = new URL(request.url);
    if (u.pathname === "/kv") return new Response((await env.REQUESTS.get("invite:smoke-token")) || "none");
    if (u.pathname === "/origin") return new Response(u.origin);
    return env.ASSETS.fetch(request);
  },
};
