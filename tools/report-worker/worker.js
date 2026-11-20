/**
 * Cloudflare Worker relay for LOTRO-TTS user reports (no user GitHub account required).
 * Creates or appends to tagged GitHub issues in ElianMoirtide/LOTRO-TTS using a server-side secret GITHUB_TOKEN.
 */

const ALLOWED_TYPES = new Set([
  "voice_quality",
  "npc_metadata",
  "pronunciation",
  "general_bug",
]);

const LABELS_BY_TYPE = {
  voice_quality: ["voice-report", "user-report"],
  npc_metadata: ["npc-metadata", "user-report"],
  pronunciation: ["pronunciation", "user-report"],
  general_bug: ["bug", "user-report"],
};

const MAX_BODY_BYTES = 24 * 1024;
const RATE_LIMIT_WINDOW_SEC = 600; // 10 minutes
const RATE_LIMIT_MAX_REQUESTS = 5;

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function cleanStr(val, maxLen = 200) {
  if (val === null || val === undefined) return "";
  return String(val)
    .replace(/\r\n/g, "\n")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .trim()
    .slice(0, maxLen);
}

function escapeMentionsAndFences(text) {
  return text
    .replace(/@/g, "@\u200B")
    .replace(/```/g, "'''");
}

async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function enforceRateLimit(request) {
  try {
    const cache = caches.default;
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const bucket = Math.floor(Date.now() / (RATE_LIMIT_WINDOW_SEC * 1000));
    const keyHash = await sha256Hex(`${ip}:${bucket}`);
    const cacheKey = new Request(`https://rate-limit.internal/lotro-tts/${keyHash}`);

    let count = 0;
    const hit = await cache.match(cacheKey);
    if (hit) {
      count = parseInt(await hit.text(), 10) || 0;
    }
    if (count >= RATE_LIMIT_MAX_REQUESTS) {
      return false;
    }
    await cache.put(
      cacheKey,
      new Response(String(count + 1), {
        headers: { "Cache-Control": `max-age=${RATE_LIMIT_WINDOW_SEC}` },
      })
    );
    return true;
  } catch {
    return true;
  }
}

async function githubFetch(env, path, options = {}) {
  const url = `https://api.github.com${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "LOTRO-TTS-Report-Worker/1.0",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(options.headers || {}),
    },
  });
  return res;
}

function buildIssueContent(report) {
  const rType = report.report_type;
  const appVer = cleanStr(report.app_version, 40) || "unknown";
  const dbVer = cleanStr(report.db_version, 40) || "unknown";
  const osInfo = cleanStr(report.os_info, 80) || "unknown";
  const clientLang = cleanStr(report.client_lang, 16) || "-";
  const ttsLang = cleanStr(report.tts_lang, 16) || "-";
  const computeMode = cleanStr(report.compute_mode, 32) || "-";
  const narratorMode = Boolean(report.narrator_mode);

  const voiceId = cleanStr(report.voice_id, 80);
  const refAudio = cleanStr(report.ref_audio, 160);
  const category = cleanStr(report.category, 60);
  const npcName = cleanStr(report.npc_name, 120);
  const npcId = cleanStr(report.npc_id, 40);
  const dbRace = cleanStr(report.db_race, 60);
  const dbGender = cleanStr(report.db_gender, 30);
  const questTitle = cleanStr(report.quest_title, 160);
  const questId = cleanStr(report.quest_id, 40);

  const expectedRace = cleanStr(report.expected_race, 60);
  const expectedGender = cleanStr(report.expected_gender, 30);
  const pronWord = cleanStr(report.pron_word, 120);
  const pronSuggestion = cleanStr(report.pron_suggestion, 160);

  const userTitle = cleanStr(report.summary, 110);
  const notes = escapeMentionsAndFences(cleanStr(report.notes, 3000));
  const logExcerpt = escapeMentionsAndFences(cleanStr(report.log_excerpt, 4000));

  let issueTitle = "";
  let dedupQuery = null;

  if (rType === "voice_quality") {
    const langTag = (ttsLang || "unknown").toLowerCase();
    const vid = voiceId || "unknown_voice";
    issueTitle = `[Voice Report] ${langTag}/${vid}`;
    if (voiceId) {
      dedupQuery = issueTitle;
    }
  } else if (rType === "npc_metadata") {
    const npcKey = npcId ? `${npcName || "NPC"} [${npcId}]` : (npcName || "Unknown NPC");
    issueTitle = `[NPC Report] ${npcKey}`;
    if (npcId || npcName) {
      dedupQuery = npcId ? `[${npcId}]` : issueTitle;
    }
  } else if (rType === "pronunciation") {
    const target = pronWord || userTitle || "Dialogue Text";
    issueTitle = `[Pronunciation] ${(ttsLang || "de").toLowerCase()}: ${target}`;
  } else {
    issueTitle = `[Bug Report] ${userTitle || "User Issue"}`;
  }

  const lines = [
    "### Submitted via LOTRO-TTS In-App Reporter",
    "",
    "| Field | Value |",
    "| :--- | :--- |",
    `| **Type** | \`${rType}\` |`,
    `| **App Version** | \`${appVer}\` |`,
    `| **DB Version** | \`${dbVer}\` |`,
    `| **OS / Mode** | \`${osInfo}\` / \`${computeMode}\` |`,
    `| **Languages** | Client: \`${clientLang}\` \\| TTS: \`${ttsLang}\` |`,
    `| **Narrator Mode** | \`${narratorMode ? "ON" : "OFF"}\` |`,
  ];

  if (voiceId || refAudio || category) {
    lines.push(`| **Voice ID** | \`${voiceId || "-"}\` (\`${category || "-"}\`) |`);
    lines.push(`| **Reference Audio** | \`${refAudio || "-"}\` |`);
  }
  if (npcName || npcId || dbRace || dbGender) {
    lines.push(`| **NPC** | \`${npcName || "-"}\` (ID: \`${npcId || "-"}\`) |`);
    lines.push(`| **Current DB Race / Gender** | \`${dbRace || "-"}\` / \`${dbGender || "-"}\` |`);
  }
  if (questTitle || questId) {
    lines.push(`| **Quest** | \`${questTitle || "-"}\` (ID: \`${questId || "-"}\`) |`);
  }
  if (rType === "npc_metadata" && (expectedRace || expectedGender)) {
    lines.push(`| **Suggested Correction** | Race: \`${expectedRace || "-"}\` \\| Gender: \`${expectedGender || "-"}\` |`);
  }
  if (rType === "pronunciation" && (pronWord || pronSuggestion)) {
    lines.push(`| **Word / Replacement** | \`${pronWord || "-"}\` → \`${pronSuggestion || "-"}\` |`);
  }

  if (userTitle) {
    lines.push("", `**Summary:** ${escapeMentionsAndFences(userTitle)}`);
  }

  lines.push("", "### Description / Notes", "", notes || "_No additional notes provided._");

  if (logExcerpt) {
    lines.push(
      "",
      "<details>",
      "<summary>Attached Log Excerpt (sanitized)</summary>",
      "",
      "```text",
      logExcerpt,
      "```",
      "",
      "</details>"
    );
  }

  const commentLines = [
    "### Additional User Report (+1)",
    "",
    `- **App / DB / OS:** \`${appVer}\` / \`${dbVer}\` / \`${osInfo}\``,
    `- **Languages:** Client \`${clientLang}\` | TTS \`${ttsLang}\` | Narrator: \`${narratorMode ? "ON" : "OFF"}\``,
  ];
  if (npcName || npcId) {
    commentLines.push(`- **NPC:** \`${npcName || "-"}\` (ID: \`${npcId || "-"}\`, DB: \`${dbRace || "-"}\` / \`${dbGender || "-"}\`)`);
  }
  if (expectedRace || expectedGender) {
    commentLines.push(`- **Suggested Correction:** Race \`${expectedRace || "-"}\` | Gender \`${expectedGender || "-"}\``);
  }
  if (notes) {
    commentLines.push("", notes);
  }

  return {
    issueTitle: issueTitle.slice(0, 140),
    issueBody: lines.join("\n"),
    commentBody: commentLines.join("\n"),
    labels: LABELS_BY_TYPE[rType] || ["user-report"],
    dedupQuery,
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && (url.pathname === "/health" || url.pathname === "/")) {
      return jsonResponse({ ok: true, service: "lotro-tts-report-worker" });
    }

    if (request.method !== "POST" || (url.pathname !== "/report" && url.pathname !== "/")) {
      return jsonResponse({ ok: false, error: "Not found" }, 404);
    }

    if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) {
      return jsonResponse({ ok: false, error: "Worker misconfigured (missing GITHUB_TOKEN or GITHUB_REPO)" }, 500);
    }

    const contentLength = parseInt(request.headers.get("content-length") || "0", 10);
    if (contentLength > MAX_BODY_BYTES) {
      return jsonResponse({ ok: false, error: "Payload too large" }, 413);
    }

    const allowed = await enforceRateLimit(request);
    if (!allowed) {
      return jsonResponse({ ok: false, error: "Rate limit exceeded. Please try again later." }, 429);
    }

    let rawText = "";
    try {
      rawText = await request.text();
    } catch {
      return jsonResponse({ ok: false, error: "Could not read request body" }, 400);
    }
    if (rawText.length > MAX_BODY_BYTES) {
      return jsonResponse({ ok: false, error: "Payload too large" }, 413);
    }

    let report;
    try {
      report = JSON.parse(rawText);
    } catch {
      return jsonResponse({ ok: false, error: "Invalid JSON body" }, 400);
    }

    if (!report || typeof report !== "object" || !ALLOWED_TYPES.has(report.report_type)) {
      return jsonResponse({ ok: false, error: "Invalid report_type" }, 400);
    }

    const notesCheck = cleanStr(report.notes, 3000);
    const summaryCheck = cleanStr(report.summary, 110);
    if (report.report_type === "general_bug" && !notesCheck && !summaryCheck) {
      return jsonResponse({ ok: false, error: "Please enter a short summary or description." }, 400);
    }
    if (report.report_type === "voice_quality" && !cleanStr(report.voice_id, 80) && !notesCheck) {
      return jsonResponse({ ok: false, error: "Voice ID or description is required." }, 400);
    }
    if (report.report_type === "npc_metadata" && !cleanStr(report.npc_name, 120) && !cleanStr(report.npc_id, 40)) {
      return jsonResponse({ ok: false, error: "NPC name or ID is required." }, 400);
    }

    const repo = env.GITHUB_REPO;
    const { issueTitle, issueBody, commentBody, labels, dedupQuery } = buildIssueContent(report);

    // Deduplicate open voice_quality / npc_metadata reports by appending a comment
    if (dedupQuery) {
      try {
        const q = encodeURIComponent(`repo:${repo} is:issue is:open "${dedupQuery}" in:title`);
        const searchRes = await githubFetch(env, `/search/issues?q=${q}&per_page=3`);
        if (searchRes.ok) {
          const searchJson = await searchRes.json();
          const match = Array.isArray(searchJson.items) && searchJson.items.length > 0 ? searchJson.items[0] : null;
          if (match && match.number) {
            const commentRes = await githubFetch(env, `/repos/${repo}/issues/${match.number}/comments`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ body: commentBody }),
            });
            if (commentRes.ok) {
              return jsonResponse({
                ok: true,
                deduplicated: true,
                issue_number: match.number,
                issue_url: match.html_url,
              });
            }
          }
        }
      } catch {
        // Fall through to creating a new issue if search failed
      }
    }

    const createRes = await githubFetch(env, `/repos/${repo}/issues`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: issueTitle,
        body: issueBody,
        labels,
      }),
    });

    if (!createRes.ok) {
      const errText = await createRes.text();
      return jsonResponse(
        { ok: false, error: `GitHub API returned ${createRes.status}: ${errText.slice(0, 200)}` },
        502
      );
    }

    const created = await createRes.json();
    return jsonResponse(
      {
        ok: true,
        deduplicated: false,
        issue_number: created.number,
        issue_url: created.html_url,
      },
      201
    );
  },
};
