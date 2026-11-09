@echo off
REM ------------------------------------------------------------------
REM Optional: copy this file to "llm-config.bat" and fill in your key.
REM start.bat loads it automatically. Without it, the local offline
REM rule engine handles everything and no network access is needed.
REM Any OpenAI-compatible /chat/completions endpoint works.
REM ------------------------------------------------------------------
set "SHORTPLAY_LLM_BASE_URL=https://api.openai.com/v1"
set "SHORTPLAY_LLM_API_KEY="
set "SHORTPLAY_LLM_MODEL=gpt-4o-mini"
REM Output budget. Reasoning models (e.g. deepseek-flash) spend this on thinking first,
REM so keep it generous or you get empty content. 16384 is a sane default.
set "SHORTPLAY_LLM_MAX_TOKENS=16384"

REM Cloud image generation (optional): Wanxiang wan2.7-image-pro, group/sequential images.
REM Get a key from your DashScope-compatible gateway, then set it below.
REM set "SHORTPLAY_DASHSCOPE_API_KEY="
REM set "SHORTPLAY_QWEN_IMAGE_SIZE=2K"

REM Example for apihub.agnes-ai.com (OpenAI compatible):
REM set "SHORTPLAY_LLM_BASE_URL=https://apihub.agnes-ai.com/v1"
REM set "SHORTPLAY_LLM_MODEL=agnes-2.0-flash"
