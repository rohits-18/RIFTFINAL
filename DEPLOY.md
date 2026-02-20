# Deployment: Deterministic Autonomous CI/CD Agent

## ⚡ Overview
This document outlines the **deterministic deployment configuration** for the Autonomous CI/CD Healing Intelligence Core. This mode is optimized for production stability, ensuring reproducible fixes and transparent model usage tracking.

## 🎛 Deterministic Mode Configuration

To ensure zero non-deterministic drift, the system is hardcoded with the following constraints:

| Component | Setting | Reason |
|DIFFERENT|---|---|
| **Model** | `gemini-1.5-flash` | **Recommended**. 1M tokens/min free limit. Rock solid stability. |
| **Provider** | `gemini` | Supports `google-generativeai` SDK. |

## 🚀 How to Run

### 1. Configure Environment (Best Practice)
Use Gemini Flash for high-volume demos:

```bash
# .env
GEMINI_API_KEY=AIza...
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-1.5-flash
```

Or use Groq (Low Volume):
```bash
GROQ_API_KEY=gsk_...
LLM_PROVIDER=groq
GROQ_MODEL=llama-3.1-8b-instant
```

### 2. Execute Pipeline
Run the agent on your target repository:

```bash
python main.py \
    --repo-path /path/to/repo \
    --repo-url  https://github.com/org/repo \
    --run-id    prod-deploy-v1 \
    --branch    main
```

The system will automatically:
1.  Detect failures (Syntax, Runtime, Logic).
2.  Attempt fixes using the **Primary Model** (`8b-instant`).
3.  If rate limits are hit, auto-switch to **Fallback Engine**.
4.  Validate fixes deterministically.

## 📊 Verifying Determinism (results.json)

Check the output `results.json` for the `llm_usage` block to confirm the execution strategy:

```json
{
  "llm_usage": {
    "primary_model": "llama-3.1-8b-instant",
    "fallback_model": "static-analysis-engine",
    "fallback_triggered": false   // true if rate limit was hit
  },
  "scoring": {
    "computation_method": "deterministic",
    "total_score": 100.0
  }
}
```

## 🌍 Production Hosting
The Intelligence Core consists of two parts:

1.  **Frontend (React)**: Best hosted on **Vercel** or **Netlify**.
2.  **Backend (Python API)**: **MUST** be hosted on a platform that supports a real Linux environment (e.g., **Railway**, **Render**, **AWS**, or **DigitalOcean**).

### Why not Vercel for the Backend?
Vercel Functions are **Serverless**. They do not include the `git` binary or the `pytest` environment needed for the agent to:
*   Clone repositories.
*   Run test suites.
*   Execute shell commands.

### 🚀 Recommended Hosting: Railway
Railway automatically detects the `Procfile` and installs all dependencies (including `git`).
1.  Connect your GitHub repo to Railway.
2.  Set your environment variables (`GEMINI_API_KEY`, `GITHUB_TOKEN`).
3.  The agent will have full access to the filesystem and git tools.

## 📊 Verifying Determinism (results.json)
...
