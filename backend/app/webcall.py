"""Browser voice-call demo page.

GET  /            → a minimal page with a "Call the receptionist" button
POST /call/web-call → creates a Retell web call, returns the access token

Lets anyone talk to the live agent from a browser — no phone number required.
Needs RETELL_API_KEY and RETELL_AGENT_ID set on the backend.
"""

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FMRI Gurgaon — AI Receptionist</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:620px;margin:8vh auto;padding:0 20px;color:#1a1a2e}
 h1{font-size:1.5rem} p{color:#555;line-height:1.5}
 button{font-size:1.1rem;padding:14px 28px;border-radius:10px;border:0;cursor:pointer;
        background:#0d7a5f;color:#fff} button:disabled{background:#999}
 #status{margin-top:16px;font-weight:600}
 .hint{font-size:.9rem;color:#777;margin-top:24px}
</style></head><body>
<h1>Fortis Memorial Research Institute, Gurgaon — AI Receptionist</h1>
<p>Click below and speak naturally: book, reschedule, or cancel an appointment
with any of FMRI's real doctors. Try “I need to see a heart doctor next week”.</p>
<button id="btn">📞 Call the receptionist</button>
<div id="status"></div>
<p class="hint">Runs on Retell (voice) + a FastAPI/Postgres backend with the hospital's
real doctor directory. Allow microphone access when prompted.</p>
<script type="module">
import { RetellWebClient } from "https://cdn.jsdelivr.net/npm/retell-client-js-sdk/+esm";
const client = new RetellWebClient();
const btn = document.getElementById("btn"), status = document.getElementById("status");
let active = false;
client.on("call_started", () => { status.textContent = "Connected — say hello!"; });
client.on("call_ended", () => { status.textContent = "Call ended."; btn.textContent = "📞 Call again"; active = false; btn.disabled = false; });
client.on("error", (e) => { status.textContent = "Error: " + (e?.message || e); active = false; btn.disabled = false; });
btn.onclick = async () => {
  if (active) { client.stopCall(); return; }
  btn.disabled = true; status.textContent = "Connecting…";
  try {
    const r = await fetch("/call/web-call", { method: "POST" });
    const d = await r.json();
    if (!d.access_token) throw new Error(d.error || "no token");
    await client.startCall({ accessToken: d.access_token });
    active = true; btn.textContent = "⏹ End call"; btn.disabled = false;
  } catch (e) { status.textContent = "Failed: " + e.message; btn.disabled = false; }
};
</script></body></html>"""


@router.get("/", response_class=HTMLResponse)
async def index():
    return PAGE


@router.post("/call/web-call")
async def create_web_call():
    api_key, agent_id = os.environ.get("RETELL_API_KEY"), os.environ.get("RETELL_AGENT_ID")
    if not api_key or not agent_id:
        return JSONResponse({"error": "web calls not configured on this deployment"}, status_code=503)
    from retell import Retell

    call = Retell(api_key=api_key).call.create_web_call(agent_id=agent_id)
    return {"access_token": call.access_token, "call_id": call.call_id}
