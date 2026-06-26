/**
 * TennisBoss API — Cloudflare Worker proxy
 *
 * Route: https://tennisboss-api.<subdomain>.workers.dev/*
 * Cible: tunnel Cloudflare privé (cfargotunnel.com) → Flask local port 8000
 *
 * Variables d'environnement (wrangler.toml [vars] ou Cloudflare Dashboard):
 *   TUNNEL_URL  → https://<UUID>.cfargotunnel.com
 *   API_TOKEN   → valeur de TENNISBOSS_API_TOKEN (optionnel)
 */

export default {
  async fetch(request, env) {
    const tunnelUrl = (env.TUNNEL_URL || "").replace(/\/$/, "");
    if (!tunnelUrl) {
      return new Response(
        JSON.stringify({ error: "TUNNEL_URL non configurée" }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      );
    }

    const origin = new URL(request.url);
    const target = tunnelUrl + origin.pathname + origin.search;

    // Recopie les headers, ajoute le token API si configuré
    const headers = new Headers(request.headers);
    headers.set("Host", new URL(tunnelUrl).host);
    if (env.API_TOKEN) {
      headers.set("X-API-Token", env.API_TOKEN);
    }

    // CORS — autorise l'app Android (OkHttp ne vérifie pas CORS,
    // mais les tests web en bénéficient)
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-API-Token, Authorization",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    try {
      const resp = await fetch(target, {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      });

      const respHeaders = new Headers(resp.headers);
      Object.entries(corsHeaders).forEach(([k, v]) => respHeaders.set(k, v));

      return new Response(resp.body, {
        status: resp.status,
        headers: respHeaders,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({ error: "API locale inaccessible", detail: String(err) }),
        { status: 502, headers: { "Content-Type": "application/json", ...corsHeaders } },
      );
    }
  },
};
